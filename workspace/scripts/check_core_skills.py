"""Check portable instructions, task provenance, package integrity and closed paths."""

import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import platform_skills as skills


def main():
    checks = []

    def check(condition, label):
        if not condition:
            raise AssertionError(label)
        checks.append(label)

    skill = skills.get("research-report")
    check(skill["authority"] == "procedure-only", "procedures do not grant execution authority")
    check(len(skill["documents"]) == 4, "entrypoint, metadata and two references bundled")
    check(
        all(
            "/home/good" not in d["content"] and "/media/good" not in d["content"]
            for d in skill["documents"]
        ),
        "no author machine paths in portable skill",
    )
    prepared = skills.task("research-report", "./my-project", "Explain mechanism and evidence")
    check(
        prepared["status"] == "awaiting_assistant" and prepared["model_calls"] == 0,
        "task preparation does not claim report execution",
    )
    check(
        all(
            d["content"] in prepared["prompt"]
            for d in skill["documents"]
            if d["path"].endswith(".md")
        ),
        "actual complete instructions and references enter assistant prompt",
    )
    archive = zipfile.ZipFile(io.BytesIO(skills.package("research-report", prepared)))
    manifest = json.loads(archive.read("MANIFEST.json"))
    check(
        manifest["revision"] == prepared["skill_revision"], "task and complete skill revision match"
    )
    for row in manifest["files"]:
        body = archive.read(row["path"])
        check(
            hashlib.sha256(body).hexdigest() == row["sha256"] and len(body) == row["bytes"],
            "SHA and length " + row["path"],
        )
    check(
        json.loads(archive.read("TASK.json"))["context"]["project"] == "./my-project",
        "project locator stays task data",
    )
    check(
        not any(
            Path(name).is_absolute() or ".." in Path(name).parts for name in archive.namelist()
        ),
        "portable zip member names",
    )
    for request in [
        dict(skill=["unknown"]),
        dict(skill=["../secret"]),
        dict(skill=["research-report"], revision=["0" * 64]),
        dict(skill=["research-report"], format=["task"], goal=["x" * 2001]),
    ]:
        try:
            skills.response(request)
        except (KeyError, ValueError):
            checks.append("invalid request rejected")
        else:
            raise AssertionError(request)
    with tempfile.TemporaryDirectory(prefix="scitaste-skill-portable-") as temp:
        root = Path(temp)
        shutil.copytree(skills.SKILLS, root / "skills")
        script = root / "workspace/scripts/platform_skills.py"
        script.parent.mkdir(parents=True)
        shutil.copyfile(Path(skills.__file__), script)
        output = subprocess.check_output(
            [sys.executable, str(script), "task", "research-report", "--project", "./elsewhere"],
            cwd=root,
            text=True,
        )
        check(
            "research-report" in output and "./elsewhere" in output,
            "relocated clone layout compiles task",
        )
        with patch.object(skills, "SKILLS", root / "skills"):
            old_revision = skills.get("research-report")["revision"]
            ref = root / "skills/research-report/references/report-template.md"
            ref.write_text(ref.read_text() + "\nAdditional reader question.\n")
            new = skills.task("research-report")
            check(
                new["skill_revision"] != old_revision
                and "Additional reader question." in new["prompt"],
                "reference changes affect revision and actual prompt",
            )
            catalog_path = root / "skills/catalog.json"
            catalog = json.loads(catalog_path.read_text())
            catalog["skills"][0]["files"].append("../catalog.json")
            catalog_path.write_text(json.dumps(catalog))
            try:
                skills.get("research-report")
            except ValueError:
                checks.append("file traversal rejected")
            else:
                raise AssertionError("traversal")
        with patch.object(skills, "MAX_PACKAGE", 1):
            try:
                skills.package("research-report")
            except ValueError:
                checks.append("package byte bound enforced")
            else:
                raise AssertionError("byte bound")
    print(json.dumps(dict(passed_checks=len(checks), checks=checks, model_calls=0)))


if __name__ == "__main__":
    main()

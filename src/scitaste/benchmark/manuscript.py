"""Deterministic Markdown-to-LaTeX packaging for audited study manuscripts."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def materialize_manuscript(
    *,
    markdown_path: Path,
    target_dir: Path,
    bibliography_path: Path | None = None,
    asset_roots: tuple[Path, ...] = (),
) -> list[Path]:
    """Create a self-contained TeX bundle and compile it when LaTeX is available."""

    markdown = markdown_path.read_text(encoding="utf-8", errors="replace")
    target_dir.mkdir(parents=True, exist_ok=True)
    markdown_target = target_dir / "main.md"
    markdown_target.write_text(markdown, encoding="utf-8")

    bibliography_target: Path | None = None
    if bibliography_path is not None and bibliography_path.is_file():
        bibliography_target = target_dir / "references.bib"
        shutil.copy2(bibliography_path, bibliography_target)

    asset_map, asset_paths = _copy_manuscript_assets(
        markdown, target_dir=target_dir, asset_roots=asset_roots
    )
    tex = markdown_to_latex(
        markdown,
        asset_map=asset_map,
        has_bibliography=bibliography_target is not None,
    )
    tex_path = target_dir / "main.tex"
    tex_path.write_text(tex, encoding="utf-8")

    readme_path = target_dir / "README.md"
    readme_path.write_text(
        "# SciTaste manuscript bundle\n\n"
        "This bundle was deterministically rendered from the evidence-audited Markdown "
        "manuscript. No additional language-model call was used.\n\n"
        "Compile locally with `latexmk -xelatex -interaction=nonstopmode "
        "-halt-on-error main.tex`.\n",
        encoding="utf-8",
    )

    build = _compile_latex_bundle(target_dir)
    build_path = target_dir / "build.json"
    build_path.write_text(json.dumps(build, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if build["status"] in {"failed", "timed_out"}:
        raise ValueError(
            f"LaTeX manuscript compilation failed; inspect {build_path} (status={build['status']})"
        )

    paths = [markdown_target, tex_path, readme_path, build_path, *asset_paths]
    if bibliography_target is not None:
        paths.append(bibliography_target)
    pdf_path = target_dir / "main.pdf"
    if pdf_path.is_file():
        paths.append(pdf_path)
    return sorted(paths)


def markdown_to_latex(
    markdown: str,
    *,
    asset_map: dict[str, str] | None = None,
    has_bibliography: bool = False,
) -> str:
    """Convert the constrained Markdown emitted by the study adapter to standalone LaTeX."""

    assets = asset_map or {}
    title, body = _extract_title(markdown)
    converted = _convert_blocks(body, assets)
    bibliography = (
        "\\bibliographystyle{plainnat}\n\\bibliography{references}\n" if has_bibliography else ""
    )
    return (
        "\\documentclass[11pt]{article}\n"
        "\\usepackage[margin=1in]{geometry}\n"
        "\\usepackage{fontspec}\n"
        "\\usepackage{microtype}\n"
        "\\usepackage{amsmath,amssymb}\n"
        "\\usepackage{booktabs,longtable,tabularx,array}\n"
        "\\usepackage{graphicx}\n"
        "\\usepackage{algorithm,algorithmic}\n"
        "\\usepackage{natbib}\n"
        "\\usepackage{xurl}\n"
        "\\usepackage[colorlinks=true,allcolors=blue]{hyperref}\n"
        "\\setlength{\\emergencystretch}{3em}\n"
        f"\\title{{{_inline_latex(title)}}}\n"
        "\\author{Anonymous Authors}\n"
        "\\date{}\n"
        "\\begin{document}\n"
        "\\maketitle\n\n"
        f"{converted.rstrip()}\n\n"
        f"{bibliography}"
        "\\end{document}\n"
    )


def _extract_title(markdown: str) -> tuple[str, str]:
    match = re.search(
        r"(?ims)^#{1,2}\s+title\s*$\s*(.+?)(?=^#{1,2}\s+|\Z)",
        markdown,
    )
    if match is None:
        return "Evidence-Bounded Study Manuscript", markdown
    title_lines = [line.strip() for line in match.group(1).splitlines() if line.strip()]
    title = re.sub(r"[*_`]", "", " ".join(title_lines))
    body = markdown[: match.start()] + markdown[match.end() :]
    return title or "Evidence-Bounded Study Manuscript", body


def _convert_blocks(markdown: str, asset_map: dict[str, str]) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None
    in_code = False
    in_display_math = False
    raw_environment: str | None = None
    abstract_open = False
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            output.append(_inline_latex(" ".join(part.strip() for part in paragraph)))
            output.append("")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_kind
        if list_kind is not None:
            output.append(f"\\end{{{list_kind}}}")
            output.append("")
            list_kind = None

    def close_abstract() -> None:
        nonlocal abstract_open
        if abstract_open:
            flush_paragraph()
            close_list()
            output.append("\\end{abstract}")
            output.append("")
            abstract_open = False

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if raw_environment is not None:
            output.append(line)
            if re.search(rf"\\end\{{{re.escape(raw_environment)}\}}", line):
                raw_environment = None
                output.append("")
            index += 1
            continue

        raw_match = re.match(r"\s*\\begin\{([A-Za-z*]+)\}", line)
        if raw_match:
            flush_paragraph()
            close_list()
            raw_environment = raw_match.group(1)
            output.append(line)
            index += 1
            continue

        if stripped.startswith("```"):
            flush_paragraph()
            close_list()
            output.append("\\end{verbatim}" if in_code else "\\begin{verbatim}")
            output.append("") if in_code else None
            in_code = not in_code
            index += 1
            continue
        if in_code:
            output.append(line)
            index += 1
            continue

        if stripped == "$$":
            flush_paragraph()
            close_list()
            output.append("\\]" if in_display_math else "\\[")
            in_display_math = not in_display_math
            index += 1
            continue
        inline_display = re.fullmatch(r"\$\$(.+)\$\$", stripped)
        if inline_display:
            flush_paragraph()
            close_list()
            output.extend(["\\[", inline_display.group(1).strip(), "\\]", ""])
            index += 1
            continue
        if stripped in {r"\[", r"\]"}:
            flush_paragraph()
            close_list()
            output.append(stripped)
            index += 1
            continue
        if in_display_math:
            output.append(line)
            index += 1
            continue

        heading = re.match(r"^(#{1,4})\s+(.+?)\s*$", line)
        if heading:
            flush_paragraph()
            close_list()
            close_abstract()
            level = len(heading.group(1))
            name = re.sub(r"^[0-9]+(?:\.[0-9]+)*[.)]?\s*", "", heading.group(2))
            canonical = re.sub(r"[*_`]", "", name).strip().casefold()
            if canonical == "abstract":
                output.append("\\begin{abstract}")
                abstract_open = True
            else:
                command = {1: "section", 2: "section", 3: "subsection", 4: "subsubsection"}[level]
                output.append(f"\\{command}{{{_inline_latex(name)}}}")
                output.append("")
            index += 1
            continue

        if (
            "|" in line
            and index + 1 < len(lines)
            and re.fullmatch(r"\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*", lines[index + 1])
        ):
            flush_paragraph()
            close_list()
            table_lines = [line]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                table_lines.append(lines[index])
                index += 1
            output.extend(_markdown_table_to_latex(table_lines))
            output.append("")
            continue

        image_match = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", stripped)
        if image_match:
            flush_paragraph()
            close_list()
            raw_target = image_match.group(2).strip().split(maxsplit=1)[0].strip("<>")
            target = asset_map.get(raw_target, raw_target)
            output.extend(
                [
                    "\\begin{figure}[htbp]",
                    "\\centering",
                    f"\\includegraphics[width=0.92\\linewidth]{{{_escape_path(target)}}}",
                    f"\\caption{{{_inline_latex(image_match.group(1))}}}",
                    "\\end{figure}",
                    "",
                ]
            )
            index += 1
            continue

        unordered = re.match(r"^\s*[-*]\s+(.+)$", line)
        ordered = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
        if unordered or ordered:
            flush_paragraph()
            wanted = "itemize" if unordered else "enumerate"
            if list_kind != wanted:
                close_list()
                output.append(f"\\begin{{{wanted}}}")
                list_kind = wanted
            item = (unordered or ordered).group(1)
            output.append(f"\\item {_inline_latex(item)}")
            index += 1
            continue

        if not stripped:
            flush_paragraph()
            close_list()
            index += 1
            continue
        if re.fullmatch(r"-{3,}", stripped):
            flush_paragraph()
            close_list()
            index += 1
            continue
        paragraph.append(stripped)
        index += 1

    flush_paragraph()
    close_list()
    close_abstract()
    if in_code:
        output.append("\\end{verbatim}")
    if in_display_math:
        output.append("\\]")
    return "\n".join(output)


def _markdown_table_to_latex(lines: list[str]) -> list[str]:
    rows = [_split_markdown_row(line) for line in lines]
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    columns = "l" + "X" * (width - 1)
    rendered = [
        "\\begin{table}[htbp]",
        "\\centering",
        "\\small",
        f"\\begin{{tabularx}}{{\\linewidth}}{{{columns}}}",
        "\\toprule",
        " & ".join(_inline_latex(cell) for cell in normalized[0]) + " \\\\",
        "\\midrule",
    ]
    rendered.extend(
        " & ".join(_inline_latex(cell) for cell in row) + " \\\\" for row in normalized[1:]
    )
    rendered.extend(["\\bottomrule", "\\end{tabularx}", "\\end{table}"])
    return rendered


def _split_markdown_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", stripped)]


def _inline_latex(text: str) -> str:
    tokens: dict[str, str] = {}

    def reserve(rendered: str) -> str:
        token = f"SCITASTETOKEN{len(tokens)}END"
        tokens[token] = rendered
        return token

    text = re.sub(r"\$[^$]+\$", lambda match: reserve(match.group(0)), text)
    text = re.sub(r"\\cite[pt]?\{[^}]+\}", lambda match: reserve(match.group(0)), text)
    text = re.sub(
        r"\[([A-Za-z][A-Za-z0-9_-]*\d{4}[A-Za-z0-9_-]*)\]",
        lambda match: reserve(f"\\citep{{{match.group(1)}}}"),
        text,
    )
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        lambda match: reserve(
            f"\\href{{{_escape_url(match.group(2))}}}{{{_escape_plain(match.group(1))}}}"
        ),
        text,
    )
    text = re.sub(
        r"\*\*(.+?)\*\*",
        lambda match: reserve(f"\\textbf{{{_escape_plain(match.group(1))}}}"),
        text,
    )
    text = re.sub(
        r"`([^`]+)`", lambda match: reserve(f"\\texttt{{{_escape_plain(match.group(1))}}}"), text
    )
    escaped = _escape_plain(text)
    for token, rendered in tokens.items():
        escaped = escaped.replace(token, rendered)
    return escaped


def _escape_plain(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in text)


def _escape_url(url: str) -> str:
    return url.replace("%", r"\%").replace("#", r"\#")


def _escape_path(path: str) -> str:
    normalized = path.replace("\\", "/").replace("}", "")
    return rf"\detokenize{{{normalized}}}"


def _copy_manuscript_assets(
    markdown: str, *, target_dir: Path, asset_roots: tuple[Path, ...]
) -> tuple[dict[str, str], list[Path]]:
    mapping: dict[str, str] = {}
    copied: list[Path] = []
    figure_dir = target_dir / "figures"
    for raw_target in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown):
        target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
        relative = Path(target)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe manuscript image path: {target}")
        source = next(
            (root / relative for root in asset_roots if (root / relative).is_file()),
            None,
        )
        if source is None:
            raise ValueError(f"manuscript image is missing: {target}")
        figure_dir.mkdir(parents=True, exist_ok=True)
        destination = figure_dir / relative.name
        if destination.exists() and destination.read_bytes() != source.read_bytes():
            prefix = hashlib.sha256(source.read_bytes()).hexdigest()[:8]
            destination = figure_dir / f"{prefix}-{relative.name}"
        shutil.copy2(source, destination)
        mapping[target] = destination.relative_to(target_dir).as_posix()
        copied.append(destination)
    return mapping, copied


def _compile_latex_bundle(target_dir: Path) -> dict[str, Any]:
    executable = shutil.which("latexmk")
    if executable is None:
        return {
            "schema_version": "1.0",
            "engine": "latexmk-xelatex",
            "status": "unavailable",
            "returncode": None,
            "pdf_generated": False,
        }
    command = [
        executable,
        "-xelatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        "main.tex",
    ]
    with tempfile.TemporaryDirectory(prefix="scitaste-manuscript-") as temporary:
        build_dir = Path(temporary)
        for path in target_dir.rglob("*"):
            relative = path.relative_to(target_dir)
            if path.is_dir():
                (build_dir / relative).mkdir(parents=True, exist_ok=True)
            elif path.name != "build.json":
                (build_dir / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, build_dir / relative)
        try:
            completed = subprocess.run(
                command,
                cwd=build_dir,
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
            stdout = completed.stdout
            stderr = completed.stderr
            built_pdf = build_dir / "main.pdf"
            if completed.returncode == 0 and built_pdf.is_file():
                shutil.copy2(built_pdf, target_dir / "main.pdf")
                status = "succeeded"
            else:
                status = "failed"
            return {
                "schema_version": "1.0",
                "engine": "latexmk-xelatex",
                "status": status,
                "returncode": completed.returncode,
                "pdf_generated": (target_dir / "main.pdf").is_file(),
                "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
                "stdout_excerpt": stdout[-8000:],
                "stderr_excerpt": stderr[-4000:],
            }
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return {
                "schema_version": "1.0",
                "engine": "latexmk-xelatex",
                "status": "timed_out",
                "returncode": None,
                "pdf_generated": False,
                "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
                "stdout_excerpt": stdout[-8000:],
                "stderr_excerpt": stderr[-4000:],
            }

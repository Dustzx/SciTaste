from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

_ROOT = Path(__file__).resolve().parents[2]
_SITE = _ROOT / "site"


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.references: list[str] = []
        self.title_parts: list[str] = []
        self.meta_names: set[str] = set()
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if identifier := values.get("id"):
            self.ids.append(identifier)
        if tag in {"a", "link"} and (href := values.get("href")):
            self.references.append(href)
        if tag in {"img", "script"} and (source := values.get("src")):
            self.references.append(source)
        if tag == "meta" and (name := values.get("name")):
            self.meta_names.add(name)
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)


def _parse_homepage() -> _PageParser:
    parser = _PageParser()
    parser.feed((_SITE / "index.html").read_text(encoding="utf-8"))
    return parser


def test_homepage_is_self_contained_and_has_closed_navigation() -> None:
    parser = _parse_homepage()
    assert len(parser.ids) == len(set(parser.ids))
    assert {"main", "taste", "workflow", "interface", "quickstart", "research"} <= set(parser.ids)
    assert {"viewport", "description", "theme-color"} <= parser.meta_names
    assert "Scientific Taste for Autonomous Research" in "".join(parser.title_parts)

    for reference in parser.references:
        parsed = urlparse(reference)
        if reference.startswith("#"):
            assert reference[1:] in parser.ids
            continue
        if parsed.scheme:
            assert parsed.scheme == "https"
            assert parsed.netloc == "github.com"
            continue
        target = (_SITE / parsed.path).resolve()
        assert target.is_relative_to(_SITE.resolve())
        assert target.is_file(), reference


def test_homepage_assets_are_bounded_and_readme_uses_the_current_title() -> None:
    hero = _SITE / "assets/scitaste-lineage.webp"
    taste_loop = _SITE / "assets/scientific-taste-loop.svg"
    assert hero.stat().st_size < 100_000
    assert (_SITE / "assets/scitaste-mark.svg").stat().st_size < 10_000
    assert taste_loop.stat().st_size < 15_000
    taste_loop_source = taste_loop.read_text(encoding="utf-8")
    assert "<title" in taste_loop_source
    assert "<desc" in taste_loop_source
    assert "Scientific Taste" in taste_loop_source

    homepage = (_SITE / "index.html").read_text(encoding="utf-8")
    assert "effectiveness claim is not yet established" in homepage
    assert "No API key" in homepage
    assert "AutoResearchClaw" in homepage

    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert "SciTaste: Improving Autonomous Research through Scientific Taste" in readme
    assert (
        "SciTaste: Learning Scientific Taste for Autonomous Research Decision Making" not in readme
    )
    assert "site/assets/scitaste-mark.svg" in readme
    assert "site/assets/scientific-taste-loop.svg" in readme
    assert "```mermaid" not in readme
    assert len(readme.splitlines()) <= 180

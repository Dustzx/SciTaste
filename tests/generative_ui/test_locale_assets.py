from __future__ import annotations

import ast
import base64
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

from scitaste.generative_ui.intent import IntentGoal
from scitaste.generative_ui.registry import ProposalKind, TrustedComponent
from scitaste.generative_ui.workspace import WorkspaceView

_STATIC = Path(__file__).parents[2] / "src/scitaste/generative_ui/static"
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def _catalog(locale: str) -> dict[str, str]:
    value = json.loads((_STATIC / f"locales/{locale}.json").read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_locale_catalogs_have_exact_key_and_interpolation_parity() -> None:
    english = _catalog("en")
    chinese = _catalog("zh-CN")

    assert english.keys() == chinese.keys()
    assert len(english) >= 300
    for key in english:
        assert re.fullmatch(r"[a-z][A-Za-z0-9_.-]+", key)
        assert isinstance(english[key], str) and english[key]
        assert isinstance(chinese[key], str) and chinese[key]
        assert Counter(_PLACEHOLDER.findall(english[key])) == Counter(
            _PLACEHOLDER.findall(chinese[key])
        )


def test_every_static_and_literal_runtime_translation_key_is_registered() -> None:
    english = _catalog("en")
    index = (_STATIC / "index.html").read_text(encoding="utf-8")
    app = (_STATIC / "app.js").read_text(encoding="utf-8")

    markup_keys = set(re.findall(r'data-i18n(?:-aria|-placeholder)?="([^"]+)"', index))
    runtime_keys = set(re.findall(r'\bt\("([^"]+)"', app))
    assert markup_keys | runtime_keys <= english.keys()
    assert 'id="locale-select"' in index
    assert "localStorage" not in app
    assert "sessionStorage" not in app
    assert "innerHTML" not in app


def test_closed_runtime_registries_have_receiver_translations() -> None:
    english = _catalog("en")

    assert {f"component.{item.value}" for item in TrustedComponent} <= english.keys()
    assert {f"action.{item.value}" for item in ProposalKind} <= english.keys()
    assert {f"title.generated.{item.value}" for item in IntentGoal} <= english.keys()
    project_views = set(WorkspaceView) - {WorkspaceView.PROJECT_LIST}
    assert {f"title.{item.value}" for item in project_views} <= english.keys()
    assert {f"view.{item.value}" for item in project_views} <= english.keys()


def test_closed_server_error_codes_have_receiver_translations() -> None:
    english = _catalog("en")
    server = ast.parse((_STATIC.parent / "server.py").read_text(encoding="utf-8"))
    codes = {
        node.args[1].value
        for node in ast.walk(server)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_HTTPProblem"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and isinstance(node.args[1].value, str)
    }

    assert codes
    assert {f"error.{code}" for code in codes} <= english.keys()


def test_locale_module_rejects_unknown_locale_and_escapes_nothing_into_markup() -> None:
    source = (_STATIC / "locale.js").read_bytes()
    module_url = "data:text/javascript;base64," + base64.b64encode(source).decode("ascii")
    script = f"""
      const locale = await import({json.dumps(module_url)});
      const catalogs = {{
        en: {{message: "Value: {{value}}"}},
        "zh-CN": {{message: "值: {{value}}"}},
      }};
      locale.validateCatalogs(catalogs);
      const payload = "<img src=x onerror=alert(1)>";
      const result = {{
        invalid: locale.localeFromHash("#/projects/demo/progress?lang=javascript:alert(1)"),
        duplicate: locale.localeFromHash("#/projects/demo/progress?lang=zh-CN&lang=en"),
        absent: locale.localeFromHash("#/projects/demo/progress"),
        route: locale.withLocale("#/projects/demo/progress?lang=en", "zh-CN"),
        fallback: locale.translateMessage(catalogs, "xx", "message", {{value: payload}}),
        chinese: locale.translateMessage(catalogs, "zh-CN", "message", {{value: payload}}),
      }};
      process.stdout.write(JSON.stringify(result));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result == {
        "invalid": "en",
        "duplicate": "en",
        "absent": None,
        "route": "#/projects/demo/progress?lang=zh-CN",
        "fallback": "Value: <img src=x onerror=alert(1)>",
        "chinese": "值: <img src=x onerror=alert(1)>",
    }


def test_catalog_text_contains_no_remote_or_executable_payloads() -> None:
    for locale in ("en", "zh-CN"):
        for value in _catalog(locale).values():
            lowered = value.lower()
            assert "<script" not in lowered
            assert "javascript:" not in lowered
            assert "https://" not in lowered
            assert "http://" not in lowered

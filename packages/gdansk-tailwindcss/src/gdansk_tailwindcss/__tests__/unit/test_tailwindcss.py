from __future__ import annotations

import re
import textwrap
import time
from typing import TYPE_CHECKING

import pytest

from gdansk_tailwindcss import TailwindCssPlugin
from gdansk_tailwindcss._core import TailwindCssTransformer

if TYPE_CHECKING:
    from pathlib import Path


def _write_tailwind_package(
    views: Path,
    *,
    package_json: str | None = None,
    build_body: str | None = None,
) -> None:
    tailwind_dir = views / "node_modules" / "tailwindcss"
    tailwind_dir.mkdir(parents=True)
    (tailwind_dir / "package.json").write_text(
        package_json
        or textwrap.dedent(
            """
            {
              "name": "tailwindcss",
              "version": "0.0.0-stub",
              "type": "module",
              "exports": {
                ".": {
                  "import": "./index.mjs",
                  "style": "./theme.css"
                }
              }
            }
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (tailwind_dir / "index.mjs").write_text(
        textwrap.dedent(
            f"""
            export async function compile(source, _opts) {{
              return {{
                build(candidates) {{
                  {build_body or "return `${source}\\n/* gdansk-tailwindcss-stub */\\n`;"}
                }},
              }};
            }}
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (tailwind_dir / "theme.css").write_text("@layer theme, base, components, utilities;\n", encoding="utf-8")


def _write_package_css_export(views: Path) -> None:
    package_dir = views / "node_modules" / "ui-kit"
    package_dir.mkdir(parents=True)
    (package_dir / "package.json").write_text(
        textwrap.dedent(
            """
            {
              "name": "ui-kit",
              "version": "0.0.0",
              "exports": {
                "./theme": {
                  "style": "./theme.css"
                }
              }
            }
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (package_dir / "theme.css").write_text(".from-package { color: red; }\n", encoding="utf-8")


def _write_views_package_json(views: Path) -> None:
    (views / "package.json").write_text('{"name":"views","version":"1.0.0"}\n', encoding="utf-8")


def test_transformer_expands_relative_css_imports(tmp_path: Path) -> None:
    views = tmp_path / "views"
    views.mkdir()
    _write_views_package_json(views)
    _write_tailwind_package(views)
    styles = views / "styles"
    styles.mkdir(parents=True)
    (styles / "other.css").write_text("/* included */\n", encoding="utf-8")

    transformer = TailwindCssTransformer(str(views))
    prepared = transformer.prepare('@import "./other.css";\n', "styles/app.css")

    assert "/* included */" in prepared.css
    assert "@import" not in prepared.css


def test_transformer_resolves_package_css_import_style_export(tmp_path: Path) -> None:
    views = tmp_path / "views"
    views.mkdir()
    _write_views_package_json(views)
    _write_tailwind_package(views)
    _write_package_css_export(views)

    transformer = TailwindCssTransformer(str(views))
    prepared = transformer.prepare('@import "ui-kit/theme";\n', "styles/app.css")

    assert ".from-package" in prepared.css


def test_transformer_skips_circular_css_imports(tmp_path: Path) -> None:
    views = tmp_path / "views"
    views.mkdir()
    _write_views_package_json(views)
    _write_tailwind_package(views)
    styles = views / "styles"
    styles.mkdir(parents=True)
    (styles / "a.css").write_text('@import "./b.css";\n.a { color: red; }\n', encoding="utf-8")
    (styles / "b.css").write_text('@import "./a.css";\n.b { color: blue; }\n', encoding="utf-8")

    transformer = TailwindCssTransformer(str(views))
    prepared = transformer.prepare('@import "./a.css";\n', "styles/app.css")

    assert ".a" in prepared.css
    assert ".b" in prepared.css
    assert "circular @import skipped" in prepared.css


def test_transformer_reports_missing_css_import(tmp_path: Path) -> None:
    views = tmp_path / "views"
    views.mkdir()
    _write_views_package_json(views)
    _write_tailwind_package(views)

    transformer = TailwindCssTransformer(str(views))

    with pytest.raises(RuntimeError, match=re.escape('failed to resolve @import "./missing.css"')):
        transformer.prepare('@import "./missing.css";\n', "styles/app.css")


def test_transformer_resolves_tailwind_entry_with_main_fallback(tmp_path: Path) -> None:
    views = tmp_path / "views"
    views.mkdir()
    _write_views_package_json(views)
    _write_tailwind_package(
        views,
        package_json=textwrap.dedent(
            """
            {
              "name": "tailwindcss",
              "version": "0.0.0-stub",
              "type": "module",
              "main": "./main.mjs"
            }
            """,
        ).strip()
        + "\n",
    )
    tailwind_dir = views / "node_modules" / "tailwindcss"
    (tailwind_dir / "main.mjs").write_text(
        "export async function compile(source) { return { build() { return source; } }; }\n",
        encoding="utf-8",
    )
    (tailwind_dir / "index.mjs").unlink()

    transformer = TailwindCssTransformer(str(views))
    prepared = transformer.prepare("body { color: red; }\n", "styles/app.css")

    assert prepared.tailwind_module_url.endswith("/main.mjs")


def test_transformer_candidate_scan_ignores_unsupported_and_ignored_paths(tmp_path: Path) -> None:
    views = tmp_path / "views"
    views.mkdir()
    _write_views_package_json(views)
    _write_tailwind_package(views)
    widget_dir = views / "widgets" / "todo"
    widget_dir.mkdir(parents=True)
    (widget_dir / "widget.tsx").write_text(
        'export default function App() { return <main className="mx-auto" />; }\n',
        encoding="utf-8",
    )
    ignored = views / "node_modules" / "ignored"
    ignored.mkdir(parents=True, exist_ok=True)
    (ignored / "index.js").write_text('export const x = "grid";\n', encoding="utf-8")
    build_dir = views / "build"
    build_dir.mkdir(parents=True)
    (build_dir / "generated.tsx").write_text('export const x = "flex";\n', encoding="utf-8")
    (views / "notes.txt").write_text("p-4\n", encoding="utf-8")

    transformer = TailwindCssTransformer(str(views))
    prepared = transformer.prepare('@import "tailwindcss";\n', "styles/app.css")

    assert "mx-auto" in prepared.candidates
    assert "grid" not in prepared.candidates
    assert "flex" not in prepared.candidates
    assert "p-4" not in prepared.candidates


def test_transformer_candidate_cache_invalidates_on_file_change(tmp_path: Path) -> None:
    views = tmp_path / "views"
    views.mkdir()
    _write_views_package_json(views)
    _write_tailwind_package(views)
    widget_dir = views / "widgets" / "todo"
    widget_dir.mkdir(parents=True)
    widget_path = widget_dir / "widget.tsx"
    widget_path.write_text(
        'export default function App() { return <main className="mx-auto" />; }\n',
        encoding="utf-8",
    )

    transformer = TailwindCssTransformer(str(views))
    first = transformer.prepare('@import "tailwindcss";\n', "styles/app.css")
    assert "mx-auto" in first.candidates

    time.sleep(0.02)
    widget_path.write_text(
        'export default function App() { return <main className="grid" />; }\n',
        encoding="utf-8",
    )

    second = transformer.prepare('@import "tailwindcss";\n', "styles/app.css")
    assert "grid" in second.candidates
    assert "mx-auto" not in second.candidates


def test_tailwind_plugin_smoke_generates_candidate_output(tmp_path: Path) -> None:
    views = tmp_path / "views"
    views.mkdir()
    _write_views_package_json(views)
    _write_tailwind_package(
        views,
        build_body=textwrap.dedent(
            """
            const out = [source];
            if (candidates.includes("mx-auto")) {
              out.push(".mx-auto{margin-inline:auto}");
            }
            return out.join("\\n");
            """,
        ).strip(),
    )
    widget_dir = views / "widgets" / "todo"
    widget_dir.mkdir(parents=True)
    (widget_dir / "widget.tsx").write_text(
        'export default function App() { return <main className="mx-auto" />; }\n',
        encoding="utf-8",
    )

    plugin = TailwindCssPlugin(package_json=views / "package.json")
    out = plugin.transform('@import "tailwindcss";\n', "styles/app.css", "css")

    assert out is not None
    assert ".mx-auto{margin-inline:auto}" in out["code"]

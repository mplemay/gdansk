from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

from gdansk_tailwindcss import TailwindCssPlugin

if TYPE_CHECKING:
    from pathlib import Path


def _write_stub_tailwind(views: Path) -> None:
    tailwind_dir = views / "node_modules" / "tailwindcss"
    tailwind_dir.mkdir(parents=True)
    (tailwind_dir / "package.json").write_text(
        textwrap.dedent(
            """
            {
              "name": "tailwindcss",
              "version": "0.0.0-stub",
              "type": "module",
              "exports": { ".": "./index.mjs" }
            }
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (tailwind_dir / "index.mjs").write_text(
        textwrap.dedent(
            """
            export async function compile(source, _opts) {
              return {
                build(_candidates) {
                  return `${source}\\n/* gdansk-tailwindcss-stub */\\n`;
                },
              };
            }
            """,
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def test_tailwind_plugin_appends_stub_marker(tmp_path: Path) -> None:
    views = tmp_path / "views"
    views.mkdir()
    (views / "package.json").write_text(
        '{"name": "v", "version": "1.0.0"}\n',
        encoding="utf-8",
    )
    _write_stub_tailwind(views)

    plugin = TailwindCssPlugin(package_json=views / "package.json")
    out = plugin.transform('@import "tailwindcss";\n', "styles/app.css", "css")
    assert out is not None
    assert "/* gdansk-tailwindcss-stub */" in out["code"]

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def write_script(tmp_path: Path):
    def write_script_file(source: str, name: str = "main.js") -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    return write_script_file


@pytest.fixture
def default_export_source() -> str:
    return """
export default function run(input) {
  return { ok: true, input };
}
"""


@pytest.fixture
def named_run_source() -> str:
    return """
export function run(input) {
  return { ok: true, input };
}
"""


def write_manifest(
    views: Path,
    *,
    assets_dir: str = "dist",
    manifest_out_dir: str | None = None,
    script: str = 'console.log("hello");\n',
    styles: list[str] | None = None,
) -> None:
    resolved_styles = styles if styles is not None else [".hello { color: red; }\n"]
    out_dir = manifest_out_dir or assets_dir
    escaped_script = script.replace("</script", "<\\/script")
    escaped_styles = [style.replace("</style", "<\\/style") for style in resolved_styles]
    html = (
        "<!DOCTYPE html>\n<html>\n<head>\n"
        + "\n".join(f"<style>{style}</style>" for style in escaped_styles)
        + '\n</head>\n<body>\n<div id="root"></div>\n'
        + f'<script type="module">{escaped_script}</script>\n'
        + "</body>\n</html>\n"
    )
    manifest: dict[str, Any] = {
        "outDir": out_dir,
        "root": str(views),
        "widgets": {
            "hello": {
                "entry": "hello/widget.tsx",
                "html": html,
            },
        },
    }

    path = views / assets_dir / "gdansk-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")

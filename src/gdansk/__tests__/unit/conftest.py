from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from gdansk.manifest import GdanskManifest

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
) -> GdanskManifest:
    resolved_styles = styles if styles is not None else [".hello { color: red; }\n"]
    out_dir = manifest_out_dir or assets_dir
    manifest: dict[str, Any] = {
        "outDir": out_dir,
        "root": str(views),
        "widgets": {
            "hello": {
                "entry": "hello/widget.tsx",
                "inline": {
                    "script": script,
                    "styles": resolved_styles,
                },
            },
        },
    }

    path = views / assets_dir / "gdansk-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return GdanskManifest.model_validate(manifest)

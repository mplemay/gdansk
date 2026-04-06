from __future__ import annotations

from typing import TYPE_CHECKING

from gdansk_bundler import AsyncBundlerContext, Bundler, BundlerOutput

if TYPE_CHECKING:
    from pathlib import Path


def write_fixture_file(root: Path, relative_path: str, contents: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def test_bundler_writes_output_and_uses_condition_names(tmp_path: Path) -> None:
    write_fixture_file(
        tmp_path,
        "node_modules/fixture-pkg/package.json",
        """
{
  "name": "fixture-pkg",
  "type": "module",
  "exports": {
    ".": {
      "python": "./python.js"
    }
  }
}
""".strip(),
    )
    write_fixture_file(
        tmp_path,
        "node_modules/fixture-pkg/python.js",
        'export default "from python condition";\n',
    )
    write_fixture_file(
        tmp_path,
        "index.ts",
        """
import message from "fixture-pkg";

console.log(message);
""".strip()
        + "\n",
    )

    bundler = Bundler(
        input={"entry": "./index.ts"},
        cwd=tmp_path,
        resolve={"condition_names": ["python"]},
        output={"dir": "dist", "format": "esm"},
    )

    with bundler() as build:
        output = build()

    assert isinstance(output, BundlerOutput)
    assert output.warnings == []
    assert (tmp_path / "dist" / "entry.js").is_file()
    assert any(chunk.file_name == "entry.js" for chunk in output.chunks)
    assert any("from python condition" in chunk.code for chunk in output.chunks)


async def test_bundler_generates_output_with_async_context(tmp_path: Path) -> None:
    write_fixture_file(
        tmp_path,
        "index.ts",
        """
export const value = 1;
console.log(value);
""".strip()
        + "\n",
    )

    bundler = Bundler(input="./index.ts", cwd=tmp_path)

    async with AsyncBundlerContext(bundler) as build:
        output = await build({"format": "esm"}, write=False)

    assert isinstance(output, BundlerOutput)
    assert len(output.chunks) == 1
    assert output.assets == []
    assert "console.log(" in output.chunks[0].code
    assert output.chunks[0].file_name == "index.js"
    assert not (tmp_path / "dist").exists()


def test_bundler_resolve_alias_and_define(tmp_path: Path) -> None:
    write_fixture_file(
        tmp_path,
        "shim.ts",
        """
export const MESSAGE = "aliased and defined";
""".strip()
        + "\n",
    )
    write_fixture_file(
        tmp_path,
        "index.ts",
        """
import { MESSAGE } from "virtual-shim";

console.log(VERSION, MESSAGE);
""".strip()
        + "\n",
    )

    bundler = Bundler(
        input="./index.ts",
        cwd=tmp_path,
        resolve={
            "alias": [
                {"find": "virtual-shim", "replacements": ["./shim.ts"]},
            ],
        },
        define={"VERSION": "'v1'"},
        output={"format": "esm"},
    )

    with bundler() as build:
        output = build(write=False)

    assert isinstance(output, BundlerOutput)
    assert output.warnings == []
    assert len(output.chunks) == 1
    assert "v1" in output.chunks[0].code
    assert "aliased and defined" in output.chunks[0].code

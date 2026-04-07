from __future__ import annotations

from typing import TYPE_CHECKING

from gdansk_bundler import AsyncBundlerContext, Bundler, BundlerOutput, Plugin

if TYPE_CHECKING:
    from pathlib import Path


def write_fixture_file(root: Path, relative_path: str, contents: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def test_bundler_resolve_id_plugin(tmp_path: Path) -> None:
    write_fixture_file(
        tmp_path,
        "real.js",
        "export const x = 42;\n",
    )
    write_fixture_file(
        tmp_path,
        "index.js",
        'import { x } from "virtual:x";\nconsole.log(x);\n',
    )

    real_js = (tmp_path / "real.js").resolve()

    class VirtualResolver(Plugin):
        def __init__(self, target: Path) -> None:
            super().__init__(name="virtual-resolver")
            self._target = target

        def resolve_id(self, spec: str, _importer: str | None) -> str | None:
            if spec == "virtual:x":
                return str(self._target)
            return None

    bundler = Bundler(
        cwd=tmp_path,
        plugins=[VirtualResolver(real_js)],
        output={"format": "esm"},
    )

    with bundler(write=False) as build:
        output = build("./index.js")

    assert isinstance(output, BundlerOutput)
    assert any("42" in chunk.code for chunk in output.chunks)


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
        cwd=tmp_path,
        resolve={"condition_names": ["python"]},
        output={"dir": "dist", "format": "esm"},
    )

    with bundler() as build:
        output = build({"entry": "./index.ts"})

    assert isinstance(output, BundlerOutput)
    assert output.warnings == []
    assert (tmp_path / "dist" / "entry.js").is_file()
    assert any(chunk.file_name == "entry.js" for chunk in output.chunks)
    assert any("from python condition" in chunk.code for chunk in output.chunks)


def test_bundler_output_override_generates_in_memory_without_default_output(tmp_path: Path) -> None:
    write_fixture_file(
        tmp_path,
        "index.ts",
        """
export const value = 1;
console.log(value);
""".strip()
        + "\n",
    )

    bundler = Bundler(cwd=tmp_path)

    with bundler() as build:
        output = build("./index.ts", {"format": "esm"})

    assert isinstance(output, BundlerOutput)
    assert len(output.chunks) == 1
    assert output.chunks[0].file_name == "index.js"
    assert not (tmp_path / "dist").exists()
    assert not (tmp_path / "index.js").exists()


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

    bundler = Bundler(cwd=tmp_path)

    async with AsyncBundlerContext(bundler, write=False) as build:
        output = await build("./index.ts", {"format": "esm"})

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
        cwd=tmp_path,
        resolve={
            "alias": [
                {"find": "virtual-shim", "replacements": ["./shim.ts"]},
            ],
        },
        define={"VERSION": "'v1'"},
        output={"format": "esm"},
    )

    with bundler(write=False) as build:
        output = build("./index.ts")

    assert isinstance(output, BundlerOutput)
    assert output.warnings == []
    assert len(output.chunks) == 1
    assert "v1" in output.chunks[0].code
    assert "aliased and defined" in output.chunks[0].code


def test_bundler_load_plugin_virtual_module(tmp_path: Path) -> None:
    virtual_id = "\x00virtual:demo"
    write_fixture_file(
        tmp_path,
        "entry.js",
        'import { answer } from "virtual:demo";\nconsole.log(answer);\n',
    )

    class VirtualLoadPlugin(Plugin):
        def __init__(self, vid: str) -> None:
            super().__init__(name="virtual-load")
            self._vid = vid

        def resolve_id(self, spec: str, _importer: str | None) -> str | None:
            if spec == "virtual:demo":
                return self._vid
            return None

        def load(self, mid: str) -> dict | None:
            if mid == self._vid:
                return {"code": "export const answer = 99;\n"}
            return None

    bundler = Bundler(
        cwd=tmp_path,
        plugins=[VirtualLoadPlugin(virtual_id)],
        output={"format": "esm"},
    )

    with bundler(write=False) as build:
        output = build("./entry.js")

    assert isinstance(output, BundlerOutput)
    assert any("99" in chunk.code for chunk in output.chunks)


def test_bundler_transform_plugin(tmp_path: Path) -> None:
    write_fixture_file(
        tmp_path,
        "entry.js",
        'export const msg = "__MARKER__";\nconsole.log(msg);\n',
    )

    class RewritePlugin(Plugin):
        def __init__(self) -> None:
            super().__init__(name="rewrite")

        def transform(self, code: str, _id: str, _module_type: str) -> dict | None:
            if "__MARKER__" in code:
                return {"code": code.replace("__MARKER__", "replaced")}
            return None

    bundler = Bundler(
        cwd=tmp_path,
        plugins=[RewritePlugin()],
        output={"format": "esm"},
    )

    with bundler(write=False) as build:
        output = build("./entry.js")

    assert isinstance(output, BundlerOutput)
    assert any("replaced" in chunk.code for chunk in output.chunks)
    assert not any("__MARKER__" in chunk.code for chunk in output.chunks)

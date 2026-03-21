from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from anyio import Path as AnyPath

from gdansk import Amber, VitePlugin
from gdansk._core import Page, bundle

REPO_ROOT = Path(__file__).resolve().parents[4]


@contextmanager
def _lifespan(app):
    loop = asyncio.new_event_loop()
    context = app.router.lifespan_context(app)
    entered = False
    try:
        loop.run_until_complete(context.__aenter__())
        entered = True
        yield
    finally:
        if entered:
            loop.run_until_complete(context.__aexit__(None, None, None))
        loop.close()


def _wait_for_css_contains(css_output: Path, text: str, *, timeout_seconds: int = 20) -> str:
    deadline = time.monotonic() + timeout_seconds
    while True:
        if css_output.exists():
            css = css_output.read_text(encoding="utf-8")
            if text in css:
                return css
        if time.monotonic() > deadline:
            pytest.fail(f"Timed out waiting for CSS output to contain {text!r}")
        time.sleep(0.1)


def _write_tailwind_vite_package(views: Path) -> None:
    package_dir = views / "node_modules" / "@tailwindcss" / "vite"
    package_dir.mkdir(parents=True, exist_ok=True)
    package_dir.joinpath("package.json").write_text(
        """
{
  "name": "@tailwindcss/vite",
  "private": true,
  "type": "module",
  "exports": {
    ".": "./index.js"
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    package_dir.joinpath("index.js").write_text(
        """
export default function tailwindVite() {
  return {
    name: "@tailwindcss/vite",
    apply: "build",
    transform: {
      filter: {
        id: {
          include: [/\\.css$/],
        },
      },
      async handler(source) {
        return `${source}\\n.mx-auto{margin-inline:auto}\\n`;
      },
    },
  };
}
""".strip()
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.integration
def test_js_plugin_transforms_bundled_css(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    amber = Amber(
        mcp=mock_mcp,
        views=pages_dir,
        plugins=[VitePlugin(specifier=Path("plugins/append-comment.mjs"), options={"comment": "from-js"})],
    )

    @amber.tool(Path("with_css/widget.tsx"))
    def my_tool():
        return "result"

    with _lifespan(amber(dev=False)):
        css_output = output / "with_css/client.css"
        assert css_output.exists()
        assert "from-js" in css_output.read_text(encoding="utf-8")


@pytest.mark.integration
def test_js_plugin_transforms_bundled_css_without_node_in_path(
    mock_mcp,
    pages_dir,
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "")
    output = pages_dir / ".gdansk"
    amber = Amber(
        mcp=mock_mcp,
        views=pages_dir,
        plugins=[VitePlugin(specifier=Path("plugins/append-comment.mjs"), options={"comment": "no-node"})],
    )

    @amber.tool(Path("with_css/widget.tsx"))
    def my_tool():
        return "result"

    with _lifespan(amber(dev=False)):
        css_output = output / "with_css/client.css"
        assert css_output.exists()
        assert "no-node" in css_output.read_text(encoding="utf-8")


@pytest.mark.integration
def test_js_plugin_watch_runs_in_dev(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    amber = Amber(
        mcp=mock_mcp,
        views=pages_dir,
        plugins=[VitePlugin(specifier=Path("plugins/append-comment.mjs"), options={"comment": "dev-js"})],
    )

    @amber.tool(Path("with_css/widget.tsx"))
    def my_tool():
        return "result"

    app = amber(dev=True)
    with _lifespan(app):
        css_output = output / "with_css/client.css"
        _wait_for_css_contains(css_output, "dev-js")


@pytest.mark.integration
def test_js_plugins_apply_in_declared_order(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    amber = Amber(
        mcp=mock_mcp,
        views=pages_dir,
        plugins=[
            VitePlugin(specifier=Path("plugins/append-comment.mjs"), options={"comment": "first"}),
            VitePlugin(specifier=Path("plugins/append-comment.mjs"), options={"comment": "second"}),
        ],
    )

    @amber.tool(Path("with_css/widget.tsx"))
    def my_tool():
        return "result"

    with _lifespan(amber(dev=False)):
        css_output = output / "with_css/client.css"
        css = css_output.read_text(encoding="utf-8")

    assert css.index("first") < css.index("second")


@pytest.mark.integration
def test_js_plugin_add_watch_file_triggers_dev_rebuild(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    watched_file = pages_dir / "comment.txt"
    watched_file.write_text("initial", encoding="utf-8")
    plugin_path = pages_dir / "plugins" / "watch-comment.mjs"
    plugin_path.parent.mkdir(parents=True, exist_ok=True)
    plugin_path.write_text(
        """
import fs from "node:fs/promises";

export default function (options) {
  return {
    name: "watch-comment",
    apply: "build",
    transform: {
      filter: {
        id: {
          include: [/\\.css$/],
        },
      },
      async handler(source, id) {
        if (!id.endsWith(".css")) {
          return source;
        }

        this.addWatchFile(options.watchFile);
        const comment = (await fs.readFile(options.watchFile, "utf8")).trim();
        return `${source}\\n/* ${comment} */\\n`;
      },
    },
  };
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    output = pages_dir / ".gdansk"
    amber = Amber(
        mcp=mock_mcp,
        views=pages_dir,
        plugins=[
            VitePlugin(
                specifier=Path("plugins/watch-comment.mjs"),
                options={"watchFile": "comment.txt"},
            ),
        ],
    )

    @amber.tool(Path("with_css/widget.tsx"))
    def my_tool():
        return "result"

    with _lifespan(amber(dev=True)):
        css_output = output / "with_css/client.css"
        _wait_for_css_contains(css_output, "initial")
        watched_file.write_text("updated", encoding="utf-8")
        css = _wait_for_css_contains(css_output, "updated")

    assert "initial" not in css


@pytest.mark.integration
def test_js_plugin_failure_surfaces_error(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    failing_plugin = pages_dir / "plugins" / "boom.mjs"
    failing_plugin.parent.mkdir(parents=True, exist_ok=True)
    failing_plugin.write_text(
        """
export default {
  name: "boom",
  async transform(source, id) {
    if (!id.endsWith(".css")) {
      return source;
    }
    throw new Error("boom");
  },
};
""".strip()
        + "\n",
        encoding="utf-8",
    )

    amber = Amber(mcp=mock_mcp, views=pages_dir, plugins=[VitePlugin(specifier=Path("plugins/boom.mjs"))])

    @amber.tool(Path("with_css/widget.tsx"))
    def my_tool():
        return "result"

    with pytest.raises(RuntimeError, match="boom"), _lifespan(amber(dev=False)):
        pass


@pytest.mark.integration
def test_js_plugin_uses_local_tailwind_vite_package(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    todo_dir = pages_dir / "widgets" / "todo"
    todo_dir.mkdir(parents=True, exist_ok=True)
    todo_dir.joinpath("widget.tsx").write_text(
        """
import "./global.css";

export default function App() {
  return <main className="mx-auto w-full max-w-xl">Todo</main>;
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    todo_dir.joinpath("global.css").write_text(
        """
body {
  color: red;
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    _write_tailwind_vite_package(pages_dir)
    output = pages_dir / ".gdansk"
    amber = Amber(
        mcp=mock_mcp,
        views=pages_dir,
        plugins=[VitePlugin(specifier="@tailwindcss/vite")],
    )

    @amber.tool(Path("todo/widget.tsx"))
    def my_tool():
        return "result"

    with _lifespan(amber(dev=False)):
        css_output = output / "todo/client.css"
        js_output = output / "todo/client.js"
        assert js_output.exists()
        assert css_output.exists()
        css = css_output.read_text(encoding="utf-8")

    assert "margin-inline:auto" in css


@pytest.mark.integration
@pytest.mark.asyncio
async def test_js_plugin_smoke_uses_repo_shadcn_tailwind_package(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    views = REPO_ROOT / "examples" / "shadcn" / "src" / "shadcn" / "views"
    output = tmp_path / "shadcn-out"

    await bundle(
        pages=[Page(path=Path("widgets/todo/widget.tsx"), is_widget=True, ssr=False)],
        dev=False,
        minify=False,
        output=output,
        cwd=views,
        plugins=[VitePlugin(specifier="@tailwindcss/vite")],
    )

    css = await AnyPath(output / "todo" / "client.css").read_text(encoding="utf-8")
    assert ".mx-auto" in css

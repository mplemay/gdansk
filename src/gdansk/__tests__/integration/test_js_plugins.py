from __future__ import annotations

import asyncio
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from anyio import Path as AnyPath

from gdansk import Ship, VitePlugin, ViteScript
from gdansk._core import Page, bundle

REPO_ROOT = Path(__file__).resolve().parents[4]


@contextmanager
def _lifespan(app, *, background: bool = False):
    loop = asyncio.new_event_loop()
    context = app.router.lifespan_context(app)
    entered = False
    loop_thread: threading.Thread | None = None
    try:
        if background:
            loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
            loop_thread.start()
            asyncio.run_coroutine_threadsafe(context.__aenter__(), loop).result()
        else:
            loop.run_until_complete(context.__aenter__())
        entered = True
        yield
    finally:
        if entered:
            if background:
                asyncio.run_coroutine_threadsafe(context.__aexit__(None, None, None), loop).result()
            else:
                loop.run_until_complete(context.__aexit__(None, None, None))
        if loop_thread is not None:
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join(timeout=5)
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


def _write_text_with_new_mtime(path: Path, contents: str, *, timeout_seconds: int = 5) -> None:
    previous_mtime = path.stat().st_mtime_ns if path.exists() else -1
    deadline = time.monotonic() + timeout_seconds
    while True:
        path.write_text(contents, encoding="utf-8")
        if path.stat().st_mtime_ns > previous_mtime:
            return
        if time.monotonic() > deadline:
            pytest.fail(f"Timed out waiting for {path} to get a newer mtime")
        time.sleep(0.01)


def _vite_plugin(script_path: Path) -> VitePlugin:
    return VitePlugin(script=ViteScript.from_file(script_path))


def _write_append_comment_plugin(views: Path, *, name: str, comment: str) -> Path:
    plugin_path = views / "plugins" / f"{name}.mjs"
    plugin_path.parent.mkdir(parents=True, exist_ok=True)
    plugin_path.write_text(
        f"""
export default {{
  name: {name!r},
  apply: "build",
  transform: {{
    filter: {{
      id: {{
        include: [/\\.css$/],
      }},
    }},
    async handler(source, id) {{
      if (!id.endsWith(".css")) {{
        return source;
      }}

      return `${{source}}\\n/* {comment} */\\n`;
    }},
  }},
}};
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return plugin_path


def _write_tailwind_wrapper_plugin(views: Path, *, specifier: str = "@tailwindcss/vite") -> Path:
    plugin_path = views / "plugins" / "tailwind-wrapper.mjs"
    plugin_path.parent.mkdir(parents=True, exist_ok=True)
    plugin_path.write_text(
        f"""
import tailwindcss from {specifier!r};

export default tailwindcss();
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return plugin_path


@pytest.mark.integration
def test_js_plugin_transforms_bundled_css(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    plugin_path = _write_append_comment_plugin(pages_dir, name="append-comment-from-js", comment="from-js")
    ship = Ship(
        mcp=mock_mcp,
        views=pages_dir,
        plugins=[_vite_plugin(plugin_path)],
    )

    @ship.tool(Path("with_css/widget.tsx"))
    def my_tool():
        return "result"

    with _lifespan(ship(dev=False)):
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
    plugin_path = _write_append_comment_plugin(pages_dir, name="append-comment-no-node", comment="no-node")
    ship = Ship(
        mcp=mock_mcp,
        views=pages_dir,
        plugins=[_vite_plugin(plugin_path)],
    )

    @ship.tool(Path("with_css/widget.tsx"))
    def my_tool():
        return "result"

    with _lifespan(ship(dev=False)):
        css_output = output / "with_css/client.css"
        assert css_output.exists()
        assert "no-node" in css_output.read_text(encoding="utf-8")


@pytest.mark.integration
def test_js_plugin_watch_runs_in_dev(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    plugin_path = _write_append_comment_plugin(pages_dir, name="append-comment-dev", comment="dev-js")
    ship = Ship(
        mcp=mock_mcp,
        views=pages_dir,
        plugins=[_vite_plugin(plugin_path)],
    )

    @ship.tool(Path("with_css/widget.tsx"))
    def my_tool():
        return "result"

    app = ship(dev=True)
    with _lifespan(app, background=True):
        css_output = output / "with_css/client.css"
        _wait_for_css_contains(css_output, "dev-js")


@pytest.mark.integration
def test_js_plugins_apply_in_declared_order(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    first_plugin = _write_append_comment_plugin(pages_dir, name="append-comment-first", comment="first")
    second_plugin = _write_append_comment_plugin(pages_dir, name="append-comment-second", comment="second")
    ship = Ship(
        mcp=mock_mcp,
        views=pages_dir,
        plugins=[
            _vite_plugin(first_plugin),
            _vite_plugin(second_plugin),
        ],
    )

    @ship.tool(Path("with_css/widget.tsx"))
    def my_tool():
        return "result"

    with _lifespan(ship(dev=False)):
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

export default {
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

      this.addWatchFile("comment.txt");
      const comment = (await fs.readFile("comment.txt", "utf8")).trim();
      return `${source}\\n/* ${comment} */\\n`;
    },
  },
};
""".strip()
        + "\n",
        encoding="utf-8",
    )

    output = pages_dir / ".gdansk"
    ship = Ship(
        mcp=mock_mcp,
        views=pages_dir,
        plugins=[
            _vite_plugin(plugin_path),
        ],
    )

    @ship.tool(Path("with_css/widget.tsx"))
    def my_tool():
        return "result"

    with _lifespan(ship(dev=True), background=True):
        css_output = output / "with_css/client.css"
        _wait_for_css_contains(css_output, "initial")
        _write_text_with_new_mtime(watched_file, "updated")
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

    ship = Ship(mcp=mock_mcp, views=pages_dir, plugins=[_vite_plugin(failing_plugin)])

    @ship.tool(Path("with_css/widget.tsx"))
    def my_tool():
        return "result"

    with pytest.raises(RuntimeError, match="boom"), _lifespan(ship(dev=False)):
        pass


@pytest.mark.integration
async def test_js_plugin_smoke_uses_repo_shadcn_tailwind_package(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    views = REPO_ROOT / "examples" / "shadcn" / "src" / "shadcn" / "views"
    output = tmp_path / "shadcn-out"

    await bundle(
        pages=[Page(path=Path("widgets/tailwind_smoke/widget.tsx"), is_widget=True, ssr=False)],
        dev=False,
        minify=False,
        output=output,
        cwd=views,
        plugins=[_vite_plugin(views / "plugins" / "tailwind-wrapper.mjs")],
    )

    css = await AnyPath(output / "tailwind_smoke" / "client.css").read_text(encoding="utf-8")
    assert ".mx-auto" in css

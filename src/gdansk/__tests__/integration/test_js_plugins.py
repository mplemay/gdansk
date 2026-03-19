from __future__ import annotations

import asyncio
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from gdansk.core import Amber
from gdansk.protocol import JsPluginSpec

_ROOT = Path(__file__).resolve().parents[4]
_SHADCN_VIEWS = _ROOT / "examples" / "shadcn" / "src" / "shadcn" / "views"


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


def _copy_shadcn_views(tmp_path: Path) -> Path:
    views = tmp_path / "views"
    shutil.copytree(
        _SHADCN_VIEWS,
        views,
        ignore=shutil.ignore_patterns("node_modules", ".gdansk"),
    )

    node_modules = _SHADCN_VIEWS / "node_modules"
    if not node_modules.is_dir():
        pytest.skip("shadcn example dependencies are not installed")

    views.joinpath("node_modules").symlink_to(node_modules, target_is_directory=True)
    return views


@pytest.mark.integration
def test_js_plugin_transforms_bundled_css(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    amber = Amber(
        mcp=mock_mcp,
        views=pages_dir,
        js_plugins=[JsPluginSpec(specifier=Path("plugins/append-comment.mjs"), options={"comment": "from-js"})],
    )

    @amber.tool(Path("with_css/page.tsx"))
    def my_tool():
        return "result"

    with _lifespan(amber(dev=False)):
        css_output = output / "with_css/client.css"
        assert css_output.exists()
        assert "from-js" in css_output.read_text(encoding="utf-8")


@pytest.mark.integration
def test_js_plugin_watch_runs_in_dev(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    amber = Amber(
        mcp=mock_mcp,
        views=pages_dir,
        js_plugins=[JsPluginSpec(specifier=Path("plugins/append-comment.mjs"), options={"comment": "dev-js"})],
    )

    @amber.tool(Path("with_css/page.tsx"))
    def my_tool():
        return "result"

    app = amber(dev=True)
    with _lifespan(app):
        css_output = output / "with_css/client.css"
        deadline = time.monotonic() + 20
        while True:
            if css_output.exists() and "dev-js" in css_output.read_text(encoding="utf-8"):
                break
            if time.monotonic() > deadline:
                pytest.fail("Timed out waiting for JS plugin output")
            time.sleep(0.1)


@pytest.mark.integration
def test_js_plugin_failure_surfaces_error(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    failing_plugin = pages_dir / "plugins" / "boom.mjs"
    failing_plugin.parent.mkdir(parents=True, exist_ok=True)
    failing_plugin.write_text(
        """
export default {
  name: "boom",
  async build() {
    throw new Error("boom");
  },
};
""".strip()
        + "\n",
        encoding="utf-8",
    )

    amber = Amber(mcp=mock_mcp, views=pages_dir, js_plugins=[JsPluginSpec(specifier=Path("plugins/boom.mjs"))])

    @amber.tool(Path("with_css/page.tsx"))
    def my_tool():
        return "result"

    with pytest.raises(RuntimeError, match="boom"), _lifespan(amber(dev=False)):
        pass


@pytest.mark.integration
def test_shadcn_example_uses_tailwind_vite_adapter(mock_mcp, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    views = _copy_shadcn_views(tmp_path)
    (views / "apps" / "todo" / "page.tsx").write_text(
        """
import "../../global.css";

export default function App() {
  return <main className="mx-auto w-full max-w-xl">Todo</main>;
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    output = views / ".gdansk"
    amber = Amber(
        mcp=mock_mcp,
        views=views,
        js_plugins=[JsPluginSpec(specifier=Path("plugins/tailwindcss.mjs"))],
    )

    @amber.tool(Path("todo/page.tsx"))
    def my_tool():
        return "result"

    with _lifespan(amber(dev=False)):
        css_output = output / "todo/client.css"
        js_output = output / "todo/client.js"
        assert js_output.exists()
        assert css_output.exists()
        css = css_output.read_text(encoding="utf-8")

    assert "margin-inline:auto" in css

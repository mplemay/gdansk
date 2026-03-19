from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from gdansk.core import Amber
from gdansk.protocol import JsPluginSpec


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

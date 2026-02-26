from __future__ import annotations

import asyncio
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from gdansk.core import Amber
from gdansk.experimental.postcss import PostCSS, PostCSSError

if TYPE_CHECKING:
    from anyio import Path as APath


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


def _create_postcss_cli(pages: Path) -> None:
    postcss_cli = pages / "node_modules" / ".bin" / "postcss"
    postcss_cli.parent.mkdir(parents=True, exist_ok=True)
    postcss_cli.write_text("", encoding="utf-8")


@pytest.mark.integration
def test_postcss_plugin_transforms_bundled_css(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    plugin = PostCSS()
    amber = Amber(mcp=mock_mcp, views=pages_dir, plugins=[plugin])

    @amber.tool(Path("with_css/page.tsx"))
    def my_tool():
        return "result"

    _create_postcss_cli(pages_dir)

    async def _transform_css(self, *, css_path: APath, cli_path: Path, pages: Path) -> None:
        _ = self
        assert cli_path == pages / "node_modules" / ".bin" / "postcss"
        original_css = await css_path.read_text(encoding="utf-8")
        await css_path.write_text(f"{original_css}\n/* transformed */\n", encoding="utf-8")

    monkeypatch.setattr(PostCSS, "_process_css_file", _transform_css)

    with _lifespan(amber(dev=False)):
        css_output = output / "with_css/client.css"
        assert css_output.exists()
        assert "/* transformed */" in css_output.read_text(encoding="utf-8")


@pytest.mark.integration
def test_postcss_plugin_failure_raises(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plugin = PostCSS()
    amber = Amber(mcp=mock_mcp, views=pages_dir, plugins=[plugin])

    @amber.tool(Path("with_css/page.tsx"))
    def my_tool():
        return "result"

    _create_postcss_cli(pages_dir)

    async def _raise_postcss_error(self, *, css_path: APath, cli_path: Path, pages: Path) -> None:
        _ = (self, cli_path, pages)
        msg = f"postcss failed for {css_path}"
        raise PostCSSError(msg)

    monkeypatch.setattr(PostCSS, "_process_css_file", _raise_postcss_error)

    with pytest.raises(PostCSSError, match="postcss failed"), _lifespan(amber(dev=False)):
        pass


@pytest.mark.integration
def test_postcss_poll_runs_in_dev(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    started = threading.Event()
    calls = 0
    plugin = PostCSS(timeout=0.01)
    amber = Amber(mcp=mock_mcp, views=pages_dir, plugins=[plugin])

    @amber.tool(Path("with_css/page.tsx"))
    def my_tool():
        return "result"

    async def _call(self, *, pages: Path, output: Path) -> None:
        _ = (self, pages, output)
        nonlocal calls
        calls += 1
        started.set()

    monkeypatch.setattr(PostCSS, "__call__", _call)

    with _lifespan(amber(dev=True)):
        assert started.wait(timeout=5)
        deadline = time.monotonic() + 5
        while calls < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert calls >= 2

from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest
from anyio import Path as APath

from gdansk.core import Amber
from gdansk.experimental.postcss import PostCSS, PostCSSError


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
    amber = Amber(mcp=mock_mcp, pages=pages_dir, plugins=[plugin])

    @amber.tool(Path("with_css/page.tsx"))
    def my_tool():
        return "result"

    _create_postcss_cli(pages_dir)

    async def _transform_css(self, *, css_path: Path, cli_path: Path, pages: Path) -> None:
        _ = self
        assert cli_path == pages / "node_modules" / ".bin" / "postcss"
        css_apath = APath(css_path)
        original_css = await css_apath.read_text(encoding="utf-8")
        await css_apath.write_text(f"{original_css}\n/* transformed */\n", encoding="utf-8")

    monkeypatch.setattr(PostCSS, "_process_css_file", _transform_css)

    with _lifespan(amber(dev=False)):
        css_output = output / "with_css/client.css"
        assert css_output.exists()
        assert "/* transformed */" in css_output.read_text(encoding="utf-8")


@pytest.mark.integration
def test_postcss_plugin_failure_raises(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plugin = PostCSS()
    amber = Amber(mcp=mock_mcp, pages=pages_dir, plugins=[plugin])

    @amber.tool(Path("with_css/page.tsx"))
    def my_tool():
        return "result"

    _create_postcss_cli(pages_dir)

    async def _raise_postcss_error(self, *, css_path: Path, cli_path: Path, pages: Path) -> None:
        _ = (self, cli_path, pages)
        msg = f"postcss failed for {css_path}"
        raise PostCSSError(msg)

    monkeypatch.setattr(PostCSS, "_process_css_file", _raise_postcss_error)

    with pytest.raises(PostCSSError, match="postcss failed"), _lifespan(amber(dev=False)):
        pass


@pytest.mark.integration
def test_postcss_watch_starts_and_stops_in_dev(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    started = threading.Event()
    stopped = threading.Event()
    cancelled = threading.Event()
    plugin = PostCSS()
    amber = Amber(mcp=mock_mcp, pages=pages_dir, plugins=[plugin])

    @amber.tool(Path("with_css/page.tsx"))
    def my_tool():
        return "result"

    async def _watch(self, *, pages: Path, output: Path, stop_event: asyncio.Event) -> None:
        _ = (self, pages, output)
        started.set()
        try:
            await stop_event.wait()
            stopped.set()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(PostCSS, "watch", _watch)

    with _lifespan(amber(dev=True)):
        assert started.wait(timeout=5)

    assert stopped.wait(timeout=5) or cancelled.wait(timeout=5)

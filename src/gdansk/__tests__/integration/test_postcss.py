from __future__ import annotations

from pathlib import Path

import pytest
from anyio import Path as APath

from gdansk.core import Amber
from gdansk.experimental.postcss import PostCSS, PostCSSError


def _create_postcss_cli(views: Path) -> None:
    postcss_cli = views / "node_modules" / ".bin" / "postcss"
    postcss_cli.parent.mkdir(parents=True, exist_ok=True)
    postcss_cli.write_text("", encoding="utf-8")


@pytest.mark.integration
def test_postcss_plugin_transforms_bundled_css(mock_mcp, views_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = views_dir / ".gdansk"
    plugin = PostCSS()
    amber = Amber(mcp=mock_mcp, views=views_dir, plugins=[plugin])

    @amber.tool(Path("with_css/app.tsx"))
    def my_tool():
        return "result"

    _create_postcss_cli(views_dir)

    async def _transform_css(self, *, css_path: Path, cli_path: Path, views: Path) -> None:
        _ = self
        assert cli_path == views / "node_modules" / ".bin" / "postcss"
        css_apath = APath(css_path)
        original_css = await css_apath.read_text(encoding="utf-8")
        await css_apath.write_text(f"{original_css}\n/* transformed */\n", encoding="utf-8")

    monkeypatch.setattr(PostCSS, "_process_css_file", _transform_css)

    with amber(blocking=True):
        css_output = output / "apps/with_css/app.css"
        assert css_output.exists()
        assert "/* transformed */" in css_output.read_text(encoding="utf-8")


@pytest.mark.integration
def test_postcss_plugin_failure_raises(mock_mcp, views_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plugin = PostCSS()
    amber = Amber(mcp=mock_mcp, views=views_dir, plugins=[plugin])

    @amber.tool(Path("with_css/app.tsx"))
    def my_tool():
        return "result"

    _create_postcss_cli(views_dir)

    async def _raise_postcss_error(self, *, css_path: Path, cli_path: Path, views: Path) -> None:
        _ = (self, cli_path, views)
        msg = f"postcss failed for {css_path}"
        raise PostCSSError(msg)

    monkeypatch.setattr(PostCSS, "_process_css_file", _raise_postcss_error)

    with pytest.raises(PostCSSError, match="postcss failed"), amber(blocking=True):
        pass

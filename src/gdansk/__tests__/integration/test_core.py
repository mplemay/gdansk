from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from gdansk.core import Amber


@pytest.mark.integration
def test_blocking_bundles_and_serves_html(mock_mcp, views_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = views_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=views_dir)

    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        return "result"

    with amber(blocking=True):
        assert (output / "apps/simple/app.js").exists()

    handler = mock_mcp._resource_calls[-1]["handler"]

    # Run handler in a properly managed event loop
    loop = asyncio.new_event_loop()
    try:
        html = loop.run_until_complete(handler())
    finally:
        loop.close()

    assert "<!DOCTYPE html>" in html
    assert '<div id="root"></div>' in html
    assert '<script type="module">' in html


@pytest.mark.integration
def test_with_css_bundles_and_serves_html(mock_mcp, views_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = views_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=views_dir)

    @amber.tool(Path("with_css/app.tsx"))
    def my_tool():
        return "result"

    with amber(blocking=True):
        assert (output / "apps/with_css/app.js").exists()
        assert (output / "apps/with_css/app.css").exists()

    handler = mock_mcp._resource_calls[-1]["handler"]
    loop = asyncio.new_event_loop()
    try:
        html = loop.run_until_complete(handler())
    finally:
        loop.close()

    assert "<style>" in html
    assert '<script type="module">' in html


@pytest.mark.integration
def test_non_blocking_bundles_in_background(mock_mcp, views_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = views_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=views_dir)

    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        return "result"

    with amber(blocking=False, dev=True):
        # Wait for the background bundler to produce output
        deadline = time.monotonic() + 20
        while not (output / "apps/simple/app.js").exists():
            if time.monotonic() > deadline:
                pytest.fail("Timed out waiting for background bundle output")
            time.sleep(0.1)

        assert (output / "apps/simple/app.js").exists()


@pytest.mark.integration
def test_multiple_tools_all_bundled(mock_mcp, views_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = views_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=views_dir)

    @amber.tool(Path("simple/app.tsx"))
    def tool_a():
        return "a"

    @amber.tool(Path("nested/page/app.tsx"))
    def tool_b():
        return "b"

    with amber(blocking=True):
        assert (output / "apps/simple/app.js").exists()
        assert (output / "apps/nested/page/app.js").exists()

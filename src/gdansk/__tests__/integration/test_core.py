from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from gdansk.core import Amber


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
def test_prod_bundles_and_serves_html(mock_mcp, views_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = views_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=views_dir)

    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        return "result"

    app = amber(dev=False)
    with _lifespan(app):
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
def test_prod_ssr_bundles_and_serves_ssr_html(mock_mcp, views_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = views_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=views_dir, ssr=True)

    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        return "result"

    app = amber(dev=False)
    with _lifespan(app):
        assert (output / "apps/simple/app.js").exists()
        assert (output / ".ssr/apps/simple/app.js").exists()

    handler = mock_mcp._resource_calls[-1]["handler"]
    loop = asyncio.new_event_loop()
    try:
        html = loop.run_until_complete(handler())
    finally:
        loop.close()

    assert '<div id="root"><div data-ssr="1"></div></div>' in html
    assert "hasChildNodes()?" in html


@pytest.mark.integration
def test_with_css_bundles_and_serves_html(mock_mcp, views_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = views_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=views_dir)

    @amber.tool(Path("with_css/app.tsx"))
    def my_tool():
        return "result"

    app = amber(dev=False)
    with _lifespan(app):
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
def test_dev_bundles_in_background(mock_mcp, views_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = views_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=views_dir)

    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        return "result"

    app = amber(dev=True)
    with _lifespan(app):
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

    app = amber(dev=False)
    with _lifespan(app):
        assert (output / "apps/simple/app.js").exists()
        assert (output / "apps/nested/page/app.js").exists()


@pytest.mark.integration
def test_prod_fails_when_ui_has_no_default_export(mock_mcp, views_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (views_dir / "apps/simple/app.tsx").write_text("export const value = 1;\n", encoding="utf-8")
    amber = Amber(mcp=mock_mcp, views=views_dir)

    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        return "result"

    app = amber(dev=False)
    with pytest.raises(RuntimeError, match="default"), _lifespan(app):
        pass


@pytest.mark.integration
def test_tool_ssr_true_overrides_amber_false(mock_mcp, views_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = views_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=views_dir, ssr=False)

    @amber.tool(Path("simple/app.tsx"), ssr=True)
    def my_tool():
        return "result"

    app = amber(dev=False)
    with _lifespan(app):
        assert (output / ".ssr/apps/simple/app.js").exists()

    handler = mock_mcp._resource_calls[-1]["handler"]
    loop = asyncio.new_event_loop()
    try:
        html = loop.run_until_complete(handler())
    finally:
        loop.close()

    assert '<div id="root"><div data-ssr="1"></div></div>' in html


@pytest.mark.integration
def test_tool_ssr_false_overrides_amber_true(mock_mcp, views_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = views_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=views_dir, ssr=True)

    @amber.tool(Path("simple/app.tsx"), ssr=False)
    def my_tool():
        return "result"

    app = amber(dev=False)
    with _lifespan(app):
        assert not (output / ".ssr/apps/simple/app.js").exists()

    handler = mock_mcp._resource_calls[-1]["handler"]
    loop = asyncio.new_event_loop()
    try:
        html = loop.run_until_complete(handler())
    finally:
        loop.close()

    assert '<div id="root"></div>' in html


@pytest.mark.integration
def test_ssr_runtime_failure_fails_fast(mock_mcp, views_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = views_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=views_dir, ssr=True)

    @amber.tool(Path("simple/app.tsx"))
    def my_tool():
        return "result"

    app = amber(dev=False)
    with _lifespan(app):
        assert (output / ".ssr/apps/simple/app.js").exists()

    (output / ".ssr/apps/simple/app.js").write_text("throw new Error('ssr boom');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(RuntimeError, match="Execution error"):
            loop.run_until_complete(handler())
    finally:
        loop.close()

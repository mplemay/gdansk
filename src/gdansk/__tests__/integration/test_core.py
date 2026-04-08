from __future__ import annotations

import asyncio
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from gdansk.core import Amber


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


@pytest.mark.integration
def test_prod_bundles_and_serves_html(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=pages_dir)

    @amber.tool(Path("simple"))
    def my_tool():
        return "result"

    app = amber(dev=False)
    with _lifespan(app):
        assert (output / "simple/client.js").exists()

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
def test_prod_ssr_bundles_and_serves_html(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=pages_dir, ssr=True)

    @amber.tool(Path("simple"))
    def my_tool():
        return "result"

    app = amber(dev=False)
    with _lifespan(app):
        assert (output / "simple/client.js").exists()
        assert (output / "simple/server.js").exists()

    handler = mock_mcp._resource_calls[-1]["handler"]
    loop = asyncio.new_event_loop()
    try:
        html = loop.run_until_complete(handler())
    finally:
        loop.close()

    assert '<div id="root"><div data-ssr="1"></div></div>' in html
    assert "hasChildNodes()" in html


@pytest.mark.integration
def test_with_css_bundles_and_serves_html(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=pages_dir)

    @amber.tool(Path("with_css/widget.tsx"))
    def my_tool():
        return "result"

    app = amber(dev=False)
    with _lifespan(app):
        assert (output / "with_css/client.js").exists()
        assert (output / "with_css/client.css").exists()

    handler = mock_mcp._resource_calls[-1]["handler"]
    loop = asyncio.new_event_loop()
    try:
        html = loop.run_until_complete(handler())
    finally:
        loop.close()

    assert "<style>" in html
    assert '<script type="module">' in html


@pytest.mark.integration
def test_with_css_bundles_when_plugin_list_is_empty(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=pages_dir, plugins=[])

    @amber.tool(Path("with_css/widget.tsx"))
    def my_tool():
        return "result"

    app = amber(dev=False)
    with _lifespan(app):
        assert (output / "with_css/client.js").exists()
        assert (output / "with_css/client.css").exists()


@pytest.mark.integration
def test_with_css_default_import_bundles(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    (pages_dir / "widgets/with_css/widget.tsx").write_text(
        """
import styles from "./simple.css";

export default function App() {
    void styles;
    return null;
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    amber = Amber(mcp=mock_mcp, views=pages_dir)

    @amber.tool(Path("with_css/widget.tsx"))
    def my_tool():
        return "result"

    app = amber(dev=False)
    with _lifespan(app):
        assert (output / "with_css/client.js").exists()
        assert (output / "with_css/client.css").exists()


@pytest.mark.integration
def test_dev_bundles_in_background(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=pages_dir)

    @amber.tool(Path("simple/widget.tsx"))
    def my_tool():
        return "result"

    app = amber(dev=True)
    with _lifespan(app, background=True):
        # Wait for the background bundler to produce output
        deadline = time.monotonic() + 20
        while not (output / "simple/client.js").exists():
            if time.monotonic() > deadline:
                pytest.fail("Timed out waiting for background bundle output")
            time.sleep(0.1)

        assert (output / "simple/client.js").exists()


@pytest.mark.integration
def test_multiple_tools_all_bundled(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=pages_dir)

    @amber.tool(Path("simple/widget.tsx"))
    def tool_a():
        return "a"

    @amber.tool(Path("nested/page/widget.tsx"))
    def tool_b():
        return "b"

    app = amber(dev=False)
    with _lifespan(app):
        assert (output / "simple/client.js").exists()
        assert (output / "nested/page/client.js").exists()


@pytest.mark.integration
def test_directory_resolution_prefers_page_tsx(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    preferred = pages_dir / "widgets" / "preferred"
    preferred.mkdir(parents=True, exist_ok=True)
    (preferred / "widget.tsx").write_text(
        "export default function App() { return <div>tsx-version</div>; }\n",
        encoding="utf-8",
    )
    (preferred / "widget.jsx").write_text(
        "export default function App() { return <div>jsx-version</div>; }\n",
        encoding="utf-8",
    )

    amber = Amber(mcp=mock_mcp, views=pages_dir)

    @amber.tool(Path("preferred"))
    def my_tool():
        return "result"

    app = amber(dev=False)
    with _lifespan(app):
        client = (output / "preferred/client.js").read_text(encoding="utf-8")

    assert "tsx-version" in client
    assert "jsx-version" not in client


@pytest.mark.integration
def test_prod_fails_when_ui_has_no_default_export(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (pages_dir / "widgets/simple/widget.tsx").write_text("export const value = 1;\n", encoding="utf-8")
    amber = Amber(mcp=mock_mcp, views=pages_dir)

    @amber.tool(Path("simple/widget.tsx"))
    def my_tool():
        return "result"

    app = amber(dev=False)
    with pytest.raises(RuntimeError, match="default"), _lifespan(app):
        pass


@pytest.mark.integration
def test_tool_ssr_true_overrides_amber_false(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=pages_dir, ssr=False)

    @amber.tool(Path("simple/widget.tsx"), ssr=True)
    def my_tool():
        return "result"

    app = amber(dev=False)
    with _lifespan(app):
        assert (output / "simple/server.js").exists()

    handler = mock_mcp._resource_calls[-1]["handler"]
    loop = asyncio.new_event_loop()
    try:
        html = loop.run_until_complete(handler())
    finally:
        loop.close()

    assert '<div id="root"><div data-ssr="1"></div></div>' in html


@pytest.mark.integration
def test_tool_ssr_false_overrides_amber_true(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=pages_dir, ssr=True)

    @amber.tool(Path("simple/widget.tsx"), ssr=False)
    def my_tool():
        return "result"

    app = amber(dev=False)
    with _lifespan(app):
        assert not (output / "simple/server.js").exists()

    handler = mock_mcp._resource_calls[-1]["handler"]
    loop = asyncio.new_event_loop()
    try:
        html = loop.run_until_complete(handler())
    finally:
        loop.close()

    assert '<div id="root"></div>' in html


@pytest.mark.integration
def test_ssr_runtime_failure_fails_fast(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=pages_dir, ssr=True)

    @amber.tool(Path("simple/widget.tsx"))
    def my_tool():
        return "result"

    app = amber(dev=False)
    with _lifespan(app):
        assert (output / "simple/server.js").exists()

    (output / "simple/server.js").write_text("throw new Error('ssr boom');", encoding="utf-8")

    handler = mock_mcp._resource_calls[-1]["handler"]
    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(RuntimeError, match="Execution error"):
            loop.run_until_complete(handler())
    finally:
        loop.close()

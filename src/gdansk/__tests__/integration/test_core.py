from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from gdansk.core import Amber, Page, Ship


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


def _write_ship_page(
    pages_dir: Path,
    relative_path: str,
    content: str = "export default function Page() { return <div>ok</div>; }\n",
) -> None:
    target = pages_dir / "app" / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


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
    assert "hasChildNodes()?" in html


@pytest.mark.integration
def test_with_css_bundles_and_serves_html(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=pages_dir)

    @amber.tool(Path("with_css/page.tsx"))
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
def test_dev_bundles_in_background(mock_mcp, pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = pages_dir / ".gdansk"
    amber = Amber(mcp=mock_mcp, views=pages_dir)

    @amber.tool(Path("simple/page.tsx"))
    def my_tool():
        return "result"

    app = amber(dev=True)
    with _lifespan(app):
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

    @amber.tool(Path("simple/page.tsx"))
    def tool_a():
        return "a"

    @amber.tool(Path("nested/page/page.tsx"))
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
    preferred = pages_dir / "apps" / "preferred"
    preferred.mkdir(parents=True, exist_ok=True)
    (preferred / "page.tsx").write_text(
        "export default function App() { return <div>tsx-version</div>; }\n",
        encoding="utf-8",
    )
    (preferred / "page.jsx").write_text(
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
    (pages_dir / "apps/simple/page.tsx").write_text("export const value = 1;\n", encoding="utf-8")
    amber = Amber(mcp=mock_mcp, views=pages_dir)

    @amber.tool(Path("simple/page.tsx"))
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

    @amber.tool(Path("simple/page.tsx"), ssr=True)
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

    @amber.tool(Path("simple/page.tsx"), ssr=False)
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

    @amber.tool(Path("simple/page.tsx"))
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


@pytest.mark.integration
def test_ship_prod_bundles_and_serves_html_when_mounted(pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_ship_page(pages_dir, "simple/page.tsx")

    ship = Ship(views=pages_dir)
    ship.include_page(page=Page(path=Path("simple/page.tsx")))

    root = Starlette()
    root.mount(path="", app=ship(dev=False))

    with TestClient(root, base_url="http://127.0.0.1:8000") as client:
        response = client.get("/simple", follow_redirects=False)

    assert response.status_code == 200
    assert "<!DOCTYPE html>" in response.text
    assert '<script type="module">' in response.text
    assert '<div id="root"></div>' in response.text
    assert (pages_dir / ".gdansk" / "app/simple/page.js").exists()


@pytest.mark.integration
def test_ship_nested_page_maps_to_nested_route(pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_ship_page(pages_dir, "a/b/page.tsx", "export default function Page() { return <div>nested-route</div>; }\n")

    ship = Ship(views=pages_dir)
    ship.include_page(page=Page(path=Path("a/b/page.tsx")))

    root = Starlette()
    root.mount(path="", app=ship(dev=False))

    with TestClient(root, base_url="http://127.0.0.1:8000") as client:
        response = client.get("/a/b", follow_redirects=False)

    assert response.status_code == 200
    assert "nested-route" in response.text


@pytest.mark.integration
def test_ship_includes_css_output(pages_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_ship_page(
        pages_dir,
        "with_css/page.tsx",
        'import "./simple.css";\nexport default function Page() { return <div>css-route</div>; }\n',
    )
    (pages_dir / "app/with_css/simple.css").write_text("body { color: blue; }\n", encoding="utf-8")

    ship = Ship(views=pages_dir)
    ship.include_page(page=Page(path=Path("with_css/page.tsx")))

    root = Starlette()
    root.mount(path="", app=ship(dev=False))

    with TestClient(root, base_url="http://127.0.0.1:8000") as client:
        response = client.get("/with_css", follow_redirects=False)

    assert response.status_code == 200
    assert "<style>" in response.text
    assert "color: blue" in response.text
    assert (pages_dir / ".gdansk" / "app/with_css/page.css").exists()


@pytest.mark.integration
@pytest.mark.parametrize(
    "dev",
    [
        False,
        True,
    ],
)
def test_ship_dev_and_prod_smoke(pages_dir, tmp_path, monkeypatch, dev):
    monkeypatch.chdir(tmp_path)
    _write_ship_page(pages_dir, "smoke/page.tsx")

    ship = Ship(views=pages_dir)
    ship.include_page(page=Page(path=Path("smoke/page.tsx")))

    root = Starlette()
    root.mount(path="", app=ship(dev=dev))

    with TestClient(root, base_url="http://127.0.0.1:8000") as client:
        response = client.get("/smoke", follow_redirects=False)

    assert response.status_code == 200
    assert (pages_dir / ".gdansk" / "app/smoke/page.js").exists()

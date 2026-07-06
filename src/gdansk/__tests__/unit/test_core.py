from __future__ import annotations

import asyncio
from copy import deepcopy
from json import dumps
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
from mcp.server import MCPServer
from mcp.server.mcpserver.tools.base import Tool
from pydantic import BaseModel

from gdansk.__tests__.unit.conftest import write_manifest
from gdansk.core import Ship
from gdansk.manifest import GdanskManifest
from gdansk.vite import Vite

if TYPE_CHECKING:
    from gdansk.task import CommandProcess
    from gdansk.widget import WidgetMeta


class SearchFilters(BaseModel):
    city: str
    radius: int = 10


def _app() -> MCPServer:
    return MCPServer(name="test")


def _stub_frontend(origin: str) -> CommandProcess:
    class StubFrontend:
        def __init__(self, origin: str) -> None:
            self.origin = origin
            self.is_running = True
            self.stopped = False

        async def stop(self) -> None:
            self.stopped = True

    return cast("CommandProcess", StubFrontend(origin))


def _stub_vite_runtime(vite: Vite, origin: str) -> None:
    vite._frontend = _stub_frontend(origin)
    runtime_path = vite.root / ".gdansk-test-runtime"
    runtime_path.mkdir(exist_ok=True)
    vite._runtime_directory = cast("Any", SimpleNamespace(name=str(runtime_path), cleanup=lambda: None))
    manifest = Path(vite._runtime_directory.name) / "manifest.json"
    manifest.write_text(
        dumps(
            {
                "root": str(vite.root),
                "widgets": {
                    "hello": {
                        "entry": "hello/widget.tsx",
                        "origin": origin,
                        "page": f"{origin}/@gdansk/page",
                    },
                },
            },
        ),
        encoding="utf-8",
    )


def test_ship_defaults_to_vite_under_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    views = tmp_path / "views"
    views.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    ship = Ship()

    assert ship._vite.root == views
    assert ship._vite.build_directory_path == views / "dist"


def test_ship_does_not_expose_static_asset_mount_surface(views_path: Path):
    ship = Ship(vite=Vite(views_path))

    assert not hasattr(ship, "assets")
    assert not hasattr(ship, "assets_path")


def test_widget_rejects_missing_widget_file(views_path: Path):
    ship = Ship(vite=Vite(views_path))

    with pytest.raises(FileNotFoundError, match="is not a file"):
        ship.widget(path=Path("missing/widget.tsx"))


def test_ship_uses_default_runtime_host_and_port(views_path: Path):
    ship = Ship(vite=Vite(views_path))

    assert ship._vite._host == "127.0.0.1"
    assert ship._vite._port == 13714


def test_ship_uses_vite_build_directory_for_manifest(views_path: Path):
    ship = Ship(vite=Vite(views_path, build_directory="public/ui"))

    assert ship._vite.build_directory_path == views_path / "public/ui"
    assert ship._vite.manifest_path == views_path / "public/ui" / "gdansk-manifest.json"


def test_ship_rejects_invalid_base_url(views_path: Path):
    with pytest.raises(ValueError, match="base URL"):
        Ship(vite=Vite(views_path), base_url="/relative")


def test_ship_widget_default_tool_and_resource_metadata(views_path: Path):
    ship = Ship(
        vite=Vite(views_path),
        base_url="https://example.com/app",
    )

    @ship.widget(path=Path("hello/widget.tsx"), name="hello", description="Widget description")
    def hello() -> None:
        return None

    spec = ship._widget_manager[Path("hello/widget.tsx")]

    assert spec.tool.meta == {
        "ui": {
            "resourceUri": "ui://hello",
        },
    }
    assert spec.resource.meta == {
        "ui": {
            "csp": {
                "connectDomains": ["https://example.com"],
                "resourceDomains": ["https://example.com"],
            },
        },
        "openai/widgetDescription": "Widget description",
    }


def test_ship_widget_preserves_explicit_metadata_split(views_path: Path):
    ship = Ship(
        vite=Vite(views_path),
        base_url="https://example.com/app",
    )
    meta: WidgetMeta = {
        "ui": {
            "resource_uri": "ui://custom",
            "prefers_border": True,
            "domain": "https://widgets.example.com",
            "csp": {
                "connect_domains": ["https://api.example.com"],
                "resource_domains": ["https://cdn.example.com"],
            },
        },
        "openai": {
            "widget_description": "Explicit widget description",
            "tool_invocation": {
                "invoking": "Calling tool",
                "invoked": "Tool complete",
            },
            "file_params": ["photo"],
        },
    }

    @ship.widget(path=Path("hello/widget.tsx"), name="hello", description="Fallback description", meta=meta)
    def hello() -> None:
        return None

    spec = ship._widget_manager[Path("hello/widget.tsx")]

    assert spec.tool.meta == {
        "ui": {
            "resourceUri": "ui://custom",
        },
        "openai/toolInvocation/invoking": "Calling tool",
        "openai/toolInvocation/invoked": "Tool complete",
        "openai/fileParams": ["photo"],
    }
    assert spec.resource.meta == {
        "ui": {
            "prefersBorder": True,
            "domain": "https://widgets.example.com",
            "csp": {
                "connectDomains": [
                    "https://api.example.com",
                    "https://example.com",
                ],
                "resourceDomains": [
                    "https://cdn.example.com",
                    "https://example.com",
                ],
            },
        },
        "openai/widgetDescription": "Explicit widget description",
        "openai/widgetPrefersBorder": True,
        "openai/widgetDomain": "https://widgets.example.com",
    }


def test_ship_widget_description_fallback_for_resource_meta(views_path: Path):
    ship = Ship(
        vite=Vite(views_path),
        base_url="https://example.com/app",
    )
    meta: WidgetMeta = {
        "ui": {
            "csp": {
                "connect_domains": ["https://api.example.com"],
            },
        },
    }

    @ship.widget(
        path=Path("hello/widget.tsx"),
        name="hello",
        description="From decorator",
        meta=meta,
    )
    def hello() -> None:
        return None

    spec = ship._widget_manager[Path("hello/widget.tsx")]

    resource_meta = spec.resource.meta
    assert resource_meta is not None
    assert resource_meta["openai/widgetDescription"] == "From decorator"


def test_ship_widget_explicit_widget_description_overrides_decorator(views_path: Path):
    ship = Ship(
        vite=Vite(views_path),
        base_url="https://example.com/app",
    )
    meta: WidgetMeta = {
        "openai": {
            "widget_description": "From meta",
        },
    }

    @ship.widget(
        path=Path("hello/widget.tsx"),
        name="hello",
        description="From decorator",
        meta=meta,
    )
    def hello() -> None:
        return None

    spec = ship._widget_manager[Path("hello/widget.tsx")]

    resource_meta = spec.resource.meta
    assert resource_meta is not None
    assert resource_meta["openai/widgetDescription"] == "From meta"


def test_ship_widget_does_not_mutate_meta_input(views_path: Path):
    ship = Ship(
        vite=Vite(views_path),
        base_url="https://example.com/app",
    )
    meta: WidgetMeta = {
        "ui": {
            "csp": {
                "connect_domains": ["https://api.example.com"],
                "resource_domains": ["https://cdn.example.com"],
            },
        },
        "openai": {
            "tool_invocation": {
                "invoking": "Calling tool",
                "invoked": "Tool complete",
            },
        },
    }
    original = deepcopy(meta)

    @ship.widget(path=Path("hello/widget.tsx"), name="hello", description="Widget description", meta=meta)
    def hello() -> None:
        return None

    assert meta == original


def test_ship_widget_default_schema_preserves_generated_tool_parameters(views_path: Path):
    ship = Ship(vite=Vite(views_path))

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello(filters: SearchFilters, name: str | None = None) -> None:
        _ = filters, name

    spec = ship._widget_manager[Path("hello/widget.tsx")]
    expected = Tool.from_function(fn=hello, name="hello").parameters

    assert spec.tool.parameters == expected


def test_ship_widget_strict_schema_normalizes_tool_parameters(views_path: Path):
    ship = Ship(vite=Vite(views_path))

    @ship.widget(path=Path("hello/widget.tsx"), name="hello", schema="strict")
    def hello(filters: SearchFilters, name: str | None = None) -> None:
        _ = filters, name

    spec = ship._widget_manager[Path("hello/widget.tsx")]

    assert spec.tool.parameters["additionalProperties"] is False
    assert spec.tool.parameters["required"] == ["filters", "name"]
    assert "default" not in spec.tool.parameters["properties"]["name"]
    assert spec.tool.parameters["properties"]["filters"] == {"$ref": "#/$defs/SearchFilters"}
    assert spec.tool.parameters["$defs"]["SearchFilters"]["additionalProperties"] is False
    assert spec.tool.parameters["$defs"]["SearchFilters"]["required"] == ["city", "radius"]
    assert spec.tool.parameters["$defs"]["SearchFilters"]["properties"]["radius"]["default"] == 10


async def test_widget_resource_renders_complete_document(views_path: Path):
    write_manifest(
        views_path,
        script='console.log("hello");\n',
        styles=[".hello { color: red; }\n"],
    )
    ship = Ship(vite=Vite(views_path))

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    ship._vite.load_manifest()

    html = await ship._widget_manager[Path("hello/widget.tsx")].resource.read()
    assert isinstance(html, str)

    assert "<!DOCTYPE html>" in html
    assert '<div id="root"></div>' in html


async def test_widget_resource_renders_production_scripts(views_path: Path):
    write_manifest(
        views_path,
        script='console.log("hello");\n',
        styles=[".hello { color: red; }\n"],
    )
    ship = Ship(vite=Vite(views_path))

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    ship._vite.load_manifest()

    html = await ship._widget_manager[Path("hello/widget.tsx")].resource.read()
    assert isinstance(html, str)

    assert "@react-refresh" not in html
    assert "__vite_plugin_react_preamble_installed__" not in html
    assert '<div id="root"></div>' in html
    assert "<style>.hello { color: red; }\n</style>" in html
    assert '<script type="module">console.log("hello");\n</script>' in html
    assert "/dist/hello/client.css" not in html
    assert "/dist/hello/client.js" not in html
    assert "/@vite/client" not in html


async def test_widget_resource_uses_custom_manifest_dir_for_inline_production(views_path: Path):
    write_manifest(
        views_path,
        assets_dir="public",
        script='console.log("custom");\n',
        styles=[".custom { color: blue; }\n"],
    )
    ship = Ship(vite=Vite(views_path, build_directory="public"))

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    ship._vite.load_manifest()

    html = await ship._widget_manager[Path("hello/widget.tsx")].resource.read()
    assert isinstance(html, str)

    assert "<style>.custom { color: blue; }\n</style>" in html
    assert '<script type="module">console.log("custom");\n</script>' in html
    assert "/public/hello/client.css" not in html
    assert "/public/hello/client.js" not in html


async def test_widget_resource_escapes_inline_closing_tags(views_path: Path):
    write_manifest(
        views_path,
        script='console.log("</script>");\n',
        styles=[".x::before { content: '</style>'; }\n"],
    )
    ship = Ship(vite=Vite(views_path), base_url="https://example.com/app")

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    ship._vite.load_manifest()

    html = await ship._widget_manager[Path("hello/widget.tsx")].resource.read()
    assert isinstance(html, str)

    assert "<\\/script>" in html
    assert "<\\/style>" in html
    assert "https://example.com/app/dist" not in html


async def test_widget_resource_raises_when_manifest_is_missing_widget(views_path: Path):
    ship = Ship(vite=Vite(views_path))

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    ship._vite._manifest = GdanskManifest(outDir="dist", root=str(views_path), widgets={})

    with pytest.raises(RuntimeError, match='does not contain the widget "hello"'):
        await ship.render_widget_page(widget_key="hello")


async def test_build_uses_task_runner(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] | None = None

    async def fake_run_script(start: Path, argv: list[str], *, local_source: str) -> None:
        nonlocal captured
        captured = {"argv": argv, "start": start, "source": local_source}

    ship = Ship(vite=Vite(views_path))
    monkeypatch.setattr("gdansk.vite.run_widget_command", fake_run_script)

    await ship._vite.build()

    assert captured is not None
    assert captured["start"] == views_path
    assert captured["argv"] == ["build", "--root", str(views_path), "--out-dir", "dist"]
    assert "buildProject" in cast("str", captured["source"])
    assert '"dist"' in cast("str", captured["source"])


async def test_wait_for_vite_timeout_mentions_matching_vite_and_plugin_config(
    views_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    def handler(request: httpx.Request) -> httpx.Response:
        msg = "connection failed"
        raise httpx.RequestError(msg, request=request)

    transport = httpx.MockTransport(handler)

    async def fake_sleep(_: float) -> None:
        return None

    async with httpx.AsyncClient(transport=transport) as client:
        vite = Vite(views_path, host="localhost", port=43123)
        _stub_vite_runtime(vite, "http://localhost:43123")
        monkeypatch.setattr("gdansk.vite.sleep", fake_sleep)

        with pytest.raises(RuntimeError) as exc_info:
            await vite.wait_until_ready(client)

    error = str(exc_info.value)
    assert "isolated widget dev servers" in error


async def test_ship_mcp_cleans_up_watch_task_on_exit(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    ship = Ship(vite=Vite(views_path))
    build_calls = 0

    async def fake_build() -> None:
        nonlocal build_calls
        build_calls += 1
        write_manifest(views_path)

    async def fake_watch_and_rebuild(_vite: Vite) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(ship._vite, "build", fake_build)
    monkeypatch.setattr("gdansk.core.watch_and_rebuild", fake_watch_and_rebuild)

    async with ship.mcp(app=_app(), watch=True):
        assert ship._active is True
        assert ship._watch_task is not None
        assert build_calls == 1
        assert 'console.log("hello");' in ship._vite.require_manifest().widgets["hello"].html

    assert ship._active is False
    assert ship._watch_task is None
    assert ship._vite._manifest is None


async def test_ship_mcp_cleans_up_on_build_failure(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    ship = Ship(vite=Vite(views_path))

    async def fake_build() -> None:
        msg = "boom"
        raise RuntimeError(msg)

    monkeypatch.setattr(ship._vite, "build", fake_build)

    with pytest.raises(RuntimeError, match="boom"):
        async with ship.mcp(app=_app(), watch=True):
            pytest.fail("Ship session should not yield after startup failure")

    assert ship._active is False
    assert ship._watch_task is None
    assert ship._vite._manifest is None


async def test_watch_mode_builds_and_starts_watch_task(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    ship = Ship(vite=Vite(views_path))
    build_calls = 0

    async def fake_build() -> None:
        nonlocal build_calls
        build_calls += 1
        write_manifest(views_path)

    async def fake_watch_and_rebuild(_vite: Vite) -> None:
        return None

    monkeypatch.setattr(ship._vite, "build", fake_build)
    monkeypatch.setattr("gdansk.core.watch_and_rebuild", fake_watch_and_rebuild)

    async with ship.mcp(app=_app(), watch=True):
        assert build_calls == 1
        assert ship._watch_task is not None
        assert 'console.log("hello");' in ship._vite.require_manifest().widgets["hello"].html


async def test_watch_mode_rebuilds_on_file_change(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    ship = Ship(vite=Vite(views_path))
    build_calls = 0

    async def fake_build() -> None:
        nonlocal build_calls
        build_calls += 1
        write_manifest(
            views_path,
            script=f'console.log("build-{build_calls}");\n',
        )

    async def fake_awatch(*_args: object, **_kwargs: object):
        yield {1}
        await asyncio.Event().wait()

    monkeypatch.setattr(ship._vite, "build", fake_build)
    monkeypatch.setattr("gdansk.watch.awatch", fake_awatch)

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    async with ship.mcp(app=_app(), watch=True):
        assert build_calls == 1
        assert 'console.log("build-1")' in ship._vite.require_manifest().widgets["hello"].html
        await asyncio.sleep(0)
        assert build_calls == 2
        assert 'console.log("build-2")' in ship._vite.require_manifest().widgets["hello"].html


async def test_start_production_builds_and_loads_manifest(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    ship = Ship(vite=Vite(views_path))

    async def fake_build() -> None:
        write_manifest(views_path)

    monkeypatch.setattr(ship._vite, "build", fake_build)

    async with ship.mcp(app=_app(), watch=False):
        assert ship._vite.has_runtime() is False
        assert 'console.log("hello");' in ship._vite.require_manifest().widgets["hello"].html

    assert ship._vite._manifest is None


async def test_start_production_requires_manifest(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    ship = Ship(vite=Vite(views_path))

    async def fake_build() -> None:
        return None

    monkeypatch.setattr(ship._vite, "build", fake_build)

    with pytest.raises(RuntimeError, match="did not produce a manifest"):
        async with ship.mcp(app=_app(), watch=False):
            pytest.fail("manifest load should fail before yield")


async def test_start_prebuilt_loads_manifest_without_build(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_manifest(views_path)
    ship = Ship(vite=Vite(views_path))

    async def fail_build() -> None:
        pytest.fail("build should not run when watch is None")

    monkeypatch.setattr(ship._vite, "build", fail_build)

    async with ship.mcp(app=_app(), watch=None):
        assert ship._vite.has_runtime() is False
        assert 'console.log("hello");' in ship._vite.require_manifest().widgets["hello"].html

    assert ship._vite._manifest is None


async def test_start_prebuilt_requires_manifest(views_path: Path):
    ship = Ship(vite=Vite(views_path))

    with pytest.raises(RuntimeError, match="did not produce a manifest"):
        async with ship.mcp(app=_app(), watch=None):
            pytest.fail("manifest load should fail before yield")


async def test_ship_mcp_open_prebuilt_skips_build(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_manifest(views_path)
    ship = Ship(vite=Vite(views_path))

    async def fail_build() -> None:
        pytest.fail("build should not run when watch is None")

    monkeypatch.setattr(ship._vite, "build", fail_build)

    async with ship.mcp(app=_app(), watch=None):
        assert ship._active is True
        assert ship._vite.has_runtime() is False
        assert 'console.log("hello");' in ship._vite.require_manifest().widgets["hello"].html

    assert ship._active is False
    assert ship._vite._manifest is None


async def test_ship_mcp_registers_widget_tool_and_resource(
    views_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    ship = Ship(vite=Vite(views_path))
    app = _app()

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    async def fake_prepare_frontend(*, watch: bool | None) -> None:
        assert watch is None

    monkeypatch.setattr(ship, "_prepare_frontend", fake_prepare_frontend)

    async with ship.mcp(app=app, watch=None):
        resources = await app.list_resources()
        resource = next((item for item in resources if item.uri == "ui://hello"), None)
        assert resource is not None
        assert resource.name == "hello"
        assert resource.mime_type == "text/html;profile=mcp-app"

        tools = await app.list_tools()
        tool = next((item for item in tools if item.name == "hello"), None)
        assert tool is not None
        assert tool.meta is not None
        assert tool.meta["ui"]["resourceUri"] == "ui://hello"


def test_load_manifest_requires_matching_build_directory(views_path: Path):
    write_manifest(views_path, assets_dir="public", manifest_out_dir="dist")
    ship = Ship(vite=Vite(views_path, build_directory="public"))

    with pytest.raises(RuntimeError, match="configured build directory"):
        ship._vite.load_manifest()


async def test_ship_mcp_rejects_reentry(views_path: Path):
    write_manifest(views_path)
    ship = Ship(vite=Vite(views_path))
    app = _app()

    async with ship.mcp(app=app, watch=None):
        with pytest.raises(RuntimeError, match="already active"):
            async with ship.mcp(app=app, watch=None):
                pytest.fail("Nested Ship session should not yield")

    assert ship._active is False

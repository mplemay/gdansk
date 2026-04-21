from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast

import httpx
import pytest
from mcp.server import MCPServer
from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.staticfiles import StaticFiles

from gdansk.__tests__.unit.conftest import FakeManagedProcess, FakeProcess, write_manifest
from gdansk.core import Ship
from gdansk.manifest import GdanskManifest
from gdansk.metadata import Metadata
from gdansk.vite import Vite

if TYPE_CHECKING:
    from gdansk.widget import WidgetMeta


class LocationSchemaModel(BaseModel):
    address: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None


LocationSchemaInput = Annotated[
    LocationSchemaModel | None,
    Field(description="Structured company location context used to disambiguate the practice when known."),
]


class CompanySchemaModel(BaseModel):
    location: Annotated[
        LocationSchemaModel | None,
        Field(description="Resolved structured practice location context."),
    ] = None


def _app() -> MCPServer:
    return MCPServer(name="test")


def test_ship_defaults_to_vite_under_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    views = tmp_path / "views"
    (views / "dist").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    ship = Ship()

    assert ship._vite.root == views
    assert ship._vite.build_directory_path == views / "dist"
    assert ship.assets_path == "/dist"
    assert isinstance(ship.assets, StaticFiles)
    assert Path(str(ship.assets.directory)) == views / "dist"


def test_ship_assets_can_be_mounted_before_build_output_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    views = tmp_path / "views"
    (views / "widgets" / "hello").mkdir(parents=True)
    (views / "widgets" / "hello" / "widget.tsx").write_text(
        "export default function App() { return null; }\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    ship = Ship()
    app = Starlette()
    app.mount(path=ship.assets_path, app=ship.assets)

    assert ship.assets_path == "/dist"
    assert Path(str(ship.assets.directory)) == views / "dist"


def test_widget_rejects_missing_widget_file(views_path: Path):
    ship = Ship(vite=Vite(views_path))

    with pytest.raises(FileNotFoundError, match="is not a file"):
        ship.widget(path=Path("missing/widget.tsx"))


def test_ship_uses_default_runtime_host_and_port(views_path: Path):
    ship = Ship(vite=Vite(views_path))

    assert ship._vite._host == "127.0.0.1"
    assert ship._vite._port == 13714
    assert ship.assets_path == "/dist"
    assert isinstance(ship.assets, StaticFiles)
    assert ship.assets is ship.assets
    assert Path(str(ship.assets.directory)) == views_path / "dist"


def test_ship_uses_vite_build_directory_for_assets(views_path: Path):
    (views_path / "public" / "ui").mkdir(parents=True)
    ship = Ship(vite=Vite(views_path, build_directory="public/ui"))

    assert ship.assets_path == "/public/ui"
    assert Path(str(ship.assets.directory)) == views_path / "public/ui"


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
            "domain": "https://example.com",
            "csp": {
                "connectDomains": ["https://example.com"],
                "resourceDomains": ["https://example.com"],
            },
        },
        "openai/widgetDescription": "Widget description",
        "openai/widgetDomain": "https://example.com",
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


def test_ship_widget_inlines_internal_input_schema_refs(views_path: Path):
    ship = Ship(vite=Vite(views_path))

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello(location: LocationSchemaInput = None) -> None:
        _ = location

    spec = ship._widget_manager[Path("hello/widget.tsx")]
    location_schema = spec.tool.parameters["properties"]["location"]

    assert "$defs" not in spec.tool.parameters
    assert location_schema["default"] is None
    assert (
        location_schema["description"]
        == "Structured company location context used to disambiguate the practice when known."
    )

    object_schema = next(option for option in location_schema["anyOf"] if option.get("type") == "object")
    assert set(object_schema["properties"]) == {"address", "city", "state", "postal_code"}


def test_ship_widget_inlines_structured_output_schema_refs_and_preserves_siblings(views_path: Path):
    ship = Ship(vite=Vite(views_path))

    @ship.widget(path=Path("hello/widget.tsx"), name="hello", structured_output=True)
    def hello() -> CompanySchemaModel:
        return CompanySchemaModel()

    spec = ship._widget_manager[Path("hello/widget.tsx")]
    assert spec.tool.output_schema is not None
    location_schema = spec.tool.output_schema["properties"]["location"]

    assert "$defs" not in spec.tool.output_schema
    assert location_schema["default"] is None
    assert location_schema["description"] == "Resolved structured practice location context."

    object_schema = next(option for option in location_schema["anyOf"] if option.get("type") == "object")
    assert set(object_schema["properties"]) == {"address", "city", "state", "postal_code"}


async def test_wait_for_vite_reads_vite_client_endpoint(views_path: Path):
    requests_seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        ship = Ship(vite=Vite(views_path), client=client)
        ship._vite._frontend = cast("Any", FakeProcess())
        ship._vite._origin = "http://runtime.test"

        await ship._vite.wait_until_ready(client)

    assert len(requests_seen) == 1
    assert str(requests_seen[0].url) == "http://runtime.test/@vite/client"
    assert requests_seen[0].extensions.get("timeout") == {"connect": 0.2, "read": 0.2, "write": 0.2, "pool": 0.2}


async def test_widget_resource_renders_complete_document(views_path: Path):
    ship = Ship(
        vite=Vite(views_path),
        metadata=Metadata(title="Base title"),
    )

    @ship.widget(path=Path("hello/widget.tsx"), name="hello", metadata=Metadata(description="Widget description"))
    def hello() -> None:
        return None

    ship._dev = True
    ship._vite._origin = "http://render.test"

    html = await ship._widget_manager[Path("hello/widget.tsx")].resource.read()
    assert isinstance(html, str)

    assert "<title>Base title</title>" in html
    assert '<meta name="description" content="Widget description" />' in html
    assert 'import RefreshRuntime from "http://render.test/@react-refresh"' in html
    assert "window.__vite_plugin_react_preamble_installed__ = true" in html
    assert '<div id="root"></div>' in html
    assert '<script type="module" src="http://render.test/@vite/client"></script>' in html
    assert '<script type="module" src="http://render.test/@gdansk/client/hello.tsx"></script>' in html


async def test_widget_resource_renders_production_scripts(views_path: Path):
    write_manifest(views_path)
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
    assert '<link rel="stylesheet" href="/dist/hello/client.css">' in html
    assert '<script type="module" src="/dist/hello/client.js"></script>' in html
    assert "/@vite/client" not in html


async def test_widget_resource_uses_custom_assets_dir_for_production_scripts(views_path: Path):
    write_manifest(views_path, assets_dir="public")
    ship = Ship(vite=Vite(views_path, build_directory="public"))

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    ship._vite.load_manifest()

    html = await ship._widget_manager[Path("hello/widget.tsx")].resource.read()
    assert isinstance(html, str)

    assert '<link rel="stylesheet" href="/public/hello/client.css">' in html
    assert '<script type="module" src="/public/hello/client.js"></script>' in html


async def test_widget_resource_uses_base_url_for_production_assets(views_path: Path):
    write_manifest(views_path)
    ship = Ship(vite=Vite(views_path), base_url="https://example.com/app")

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    ship._vite.load_manifest()

    html = await ship._widget_manager[Path("hello/widget.tsx")].resource.read()
    assert isinstance(html, str)

    assert '<link rel="stylesheet" href="https://example.com/app/dist/hello/client.css">' in html
    assert '<script type="module" src="https://example.com/app/dist/hello/client.js"></script>' in html


async def test_widget_resource_raises_when_manifest_is_missing_widget(views_path: Path):
    ship = Ship(vite=Vite(views_path))

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    ship._vite._manifest = GdanskManifest(outDir="dist", root=str(views_path), widgets={})

    with pytest.raises(RuntimeError, match='does not contain the widget "hello"'):
        await ship.render_widget_page(metadata=None, widget_key="hello")


async def test_build_uses_the_root_vite_entrypoint(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    captured_args: tuple[str, ...] | None = None
    captured_kwargs: dict[str, object] | None = None

    class FakeBuildProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

    async def fake_create_subprocess_exec(*args: str, **kwargs: object) -> FakeBuildProcess:
        nonlocal captured_args, captured_kwargs
        captured_args = args
        captured_kwargs = kwargs
        return FakeBuildProcess()

    ship = Ship(vite=Vite(views_path))
    monkeypatch.setattr("gdansk.vite.create_subprocess_exec", fake_create_subprocess_exec)

    await ship._vite.build()

    assert captured_args == (
        ship._vite._deno,
        "run",
        "-A",
        "--node-modules-dir=auto",
        "npm:vite",
        "build",
    )
    assert captured_kwargs is not None
    assert captured_kwargs["cwd"] == views_path
    assert "env" not in captured_kwargs


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
        ship = Ship(
            vite=Vite(views_path, host="localhost", port=43123),
            client=client,
        )
        ship._vite._frontend = cast("Any", FakeProcess())
        ship._vite._origin = "http://localhost:43123"
        monkeypatch.setattr("gdansk.vite.sleep", fake_sleep)

        with pytest.raises(RuntimeError) as exc_info:
            await ship._vite.wait_until_ready(client)

    error = str(exc_info.value)
    assert 'Ensure Vite(host="localhost", port=43123)' in error
    assert 'gdansk({ host: "localhost", port: 43123 })' in error


async def test_ship_mcp_cleans_up_runtime_on_exit(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    process = FakeManagedProcess()
    ship = Ship(vite=Vite(views_path))

    async def fake_create_subprocess_exec(*_args: str, **_kwargs: object) -> FakeManagedProcess:
        return process

    async def fake_wait_until_ready(_client: httpx.AsyncClient) -> None:
        return None

    monkeypatch.setattr("gdansk.vite.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(ship._vite, "wait_until_ready", fake_wait_until_ready)

    async with ship.mcp(app=_app(), watch=True):
        assert ship._active is True
        assert ship._dev is True
        assert ship._vite._frontend is process
        assert ship._vite._origin == "http://127.0.0.1:13714"

    assert process.terminated is True
    assert process.killed is False
    assert process.waited is False
    assert ship._active is False
    assert ship._dev is False
    assert ship._vite._frontend is None
    assert ship._vite._origin is None
    assert ship._vite._manifest is None
    assert ship._session_client is None


async def test_ship_mcp_cleans_up_runtime_on_start_failure(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    process = FakeManagedProcess()
    ship = Ship(vite=Vite(views_path))

    async def fake_create_subprocess_exec(*_args: str, **_kwargs: object) -> FakeManagedProcess:
        return process

    async def fake_wait_until_ready(_client: httpx.AsyncClient) -> None:
        msg = "boom"
        raise RuntimeError(msg)

    monkeypatch.setattr("gdansk.vite.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(ship._vite, "wait_until_ready", fake_wait_until_ready)

    with pytest.raises(RuntimeError, match="boom"):
        async with ship.mcp(app=_app(), watch=True):
            pytest.fail("Ship session should not yield after startup failure")

    assert process.terminated is True
    assert process.killed is False
    assert process.waited is False
    assert ship._active is False
    assert ship._dev is False
    assert ship._vite._frontend is None
    assert ship._vite._origin is None
    assert ship._vite._manifest is None
    assert ship._session_client is None


async def test_ship_mcp_preserves_startup_error_when_runtime_exits_during_cleanup(
    views_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class VanishedProcess:
        def __init__(self) -> None:
            self.kill_calls = 0
            self.returncode: int | None = None
            self.terminate_calls = 0
            self.wait_calls = 0

        def terminate(self) -> None:
            self.terminate_calls += 1
            raise ProcessLookupError

        def kill(self) -> None:
            self.kill_calls += 1
            raise ProcessLookupError

        async def wait(self) -> int:
            self.wait_calls += 1
            self.returncode = 1
            return self.returncode

    async def fake_create_subprocess_exec(*_args: str, **_kwargs: object) -> VanishedProcess:
        return process

    async def fake_sleep(_: float) -> None:
        return None

    async def fake_wait_until_ready(_client: httpx.AsyncClient) -> None:
        msg = "boom"
        raise RuntimeError(msg)

    process = VanishedProcess()
    ship = Ship(vite=Vite(views_path))
    monkeypatch.setattr("gdansk.vite.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr("gdansk.vite.sleep", fake_sleep)
    monkeypatch.setattr(ship._vite, "wait_until_ready", fake_wait_until_ready)

    with pytest.raises(RuntimeError, match="boom"):
        async with ship.mcp(app=_app(), watch=True):
            pytest.fail("Ship session should not yield after startup failure")

    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.wait_calls == 1
    assert ship._active is False
    assert ship._dev is False
    assert ship._vite._frontend is None
    assert ship._vite._origin is None
    assert ship._vite._manifest is None


async def test_start_dev_uses_runtime_port(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    captured_args: tuple[str, ...] | None = None

    async def fake_create_subprocess_exec(*args: str, **_kwargs: object) -> FakeManagedProcess:
        nonlocal captured_args
        captured_args = args
        return FakeManagedProcess()

    async def fake_wait_until_ready(_client: httpx.AsyncClient) -> None:
        return None

    ship = Ship(vite=Vite(views_path, port=43123))
    monkeypatch.setattr("gdansk.vite.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(ship._vite, "wait_until_ready", fake_wait_until_ready)

    async with ship.mcp(app=_app(), watch=True):
        pass

    assert captured_args == (
        ship._vite._deno,
        "run",
        "-A",
        "--node-modules-dir=auto",
        "npm:vite",
        "dev",
        "--host",
        "127.0.0.1",
        "--port",
        "43123",
        "--strictPort",
    )


async def test_start_production_builds_and_loads_manifest(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    ship = Ship(vite=Vite(views_path))

    async def fake_build() -> None:
        write_manifest(views_path)

    monkeypatch.setattr(ship._vite, "build", fake_build)

    async with ship.mcp(app=_app(), watch=False):
        assert ship._vite._frontend is None
        assert ship._vite.require_manifest().widgets["hello"].client == "dist/hello/client.js"
        assert ship._vite._origin is None

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
        assert ship._vite._frontend is None
        assert ship._vite.require_manifest().widgets["hello"].client == "dist/hello/client.js"
        assert ship._vite._origin is None
        assert ship._dev is False

    assert ship._vite._manifest is None


async def test_start_prebuilt_requires_manifest(views_path: Path):
    ship = Ship(vite=Vite(views_path))

    with pytest.raises(RuntimeError, match="did not produce a manifest"):
        async with ship.mcp(app=_app(), watch=None):
            pytest.fail("manifest load should fail before yield")


async def test_ship_mcp_open_prebuilt_skips_subprocess(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_manifest(views_path)
    ship = Ship(vite=Vite(views_path))

    async def fail_create_subprocess_exec(*_args: str, **_kwargs: object) -> FakeManagedProcess:
        pytest.fail("create_subprocess_exec should not run when watch is None")

    monkeypatch.setattr("gdansk.vite.create_subprocess_exec", fail_create_subprocess_exec)

    async with ship.mcp(app=_app(), watch=None):
        assert ship._active is True
        assert ship._dev is False
        assert ship._vite._frontend is None
        assert ship._vite.require_manifest().widgets["hello"].client == "dist/hello/client.js"
        assert ship._vite._origin is None

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

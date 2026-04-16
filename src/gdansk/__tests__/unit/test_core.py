from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from httpx import Request, RequestError
from starlette.staticfiles import StaticFiles

from gdansk.core import Ship
from gdansk.metadata import Metadata

if TYPE_CHECKING:
    from httpx import AsyncClient

    from gdansk.widget import WidgetMeta


class FakeResponse:
    def __init__(
        self,
        *,
        body: str = "",
        head: list[str] | None = None,
        payload: dict[str, Any] | None = None,
        status_code: int = 200,
        raw_text: str | None = None,
    ) -> None:
        self._payload = payload if payload is not None else {"body": body, "head": head or []}
        self.status_code = status_code
        self.text = raw_text if raw_text is not None else json.dumps(self._payload)

    def json(self) -> dict[str, Any]:
        return cast("dict[str, Any]", self._payload)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.get_calls: list[tuple[str, float | None]] = []
        self.health_payload: dict[str, Any] = {"status": "OK"}
        self.render_payload: dict[str, Any] | None = None

    async def get(self, url: str, **kwargs: float | None) -> FakeResponse:
        timeout = kwargs.get("timeout")
        self.get_calls.append((url, timeout))
        return FakeResponse(payload=self.health_payload)

    async def post(self, url: str, *, json: dict[str, str]) -> FakeResponse:
        self.calls.append((url, json))
        if self.render_payload is not None:
            return FakeResponse(payload=self.render_payload)
        return FakeResponse(
            body="<main>Hello from production</main>",
            head=['<meta name="robots" content="noindex" />'],
        )


class FakeProcess:
    returncode: int | None = None


class FakeManagedProcess:
    def __init__(self) -> None:
        self.killed = False
        self.returncode: int | None = None
        self.terminated = False
        self.waited = False

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        self.waited = True
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


@pytest.fixture
def views_path(tmp_path: Path) -> Path:
    views = tmp_path / "views"
    (views / "widgets" / "hello").mkdir(parents=True)
    (views / "widgets" / "hello" / "widget.tsx").write_text("export default function App() { return null; }\n")
    return views


def write_manifest(views: Path, *, assets_dir: str = "dist") -> None:
    manifest: dict[str, Any] = {
        "outDir": assets_dir,
        "root": str(views),
        "widgets": {
            "hello": {
                "client": f"{assets_dir}/hello/client.js",
                "css": [f"{assets_dir}/hello/client.css"],
                "entry": "hello/widget.tsx",
            },
        },
    }
    manifest["server"] = f"{assets_dir}/render.js"

    path = views / assets_dir / "gdansk-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_widget_rejects_missing_widget_file(views_path: Path):
    ship = Ship(views=views_path)

    with pytest.raises(FileNotFoundError, match="is not a file"):
        ship.widget(path=Path("missing/widget.tsx"))


def test_ship_uses_default_runtime_host_and_port(views_path: Path):
    ship = Ship(views=views_path)

    assert ship._host == "127.0.0.1"
    assert ship._port == 13714
    assert isinstance(ship.assets, StaticFiles)
    assert ship.assets is ship.assets
    assert Path(str(ship.assets.directory)) == views_path / "dist"


def test_ship_rejects_invalid_runtime_port(views_path: Path):
    with pytest.raises(ValueError, match="runtime port"):
        Ship(views=views_path, port=0)


def test_ship_rejects_invalid_base_url(views_path: Path):
    with pytest.raises(ValueError, match="base URL"):
        Ship(views=views_path, base_url="/relative")


def test_ship_supports_custom_widgets_directory(tmp_path: Path):
    views = tmp_path / "views"
    (views / "ui" / "widgets" / "hello").mkdir(parents=True)
    (views / "ui" / "widgets" / "hello" / "widget.tsx").write_text("export default function App() { return null; }\n")

    ship = Ship(views=views, widgets_directory="ui/widgets")

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    assert ship._widgets_root == views / "ui" / "widgets"
    assert Path("hello/widget.tsx") in ship._widget_manager


def test_ship_rejects_invalid_widgets_directory(views_path: Path):
    with pytest.raises(ValueError, match="widgets directory"):
        Ship(views=views_path, widgets_directory="../widgets")


async def test_wait_for_health_reads_endpoint(views_path: Path):
    client = FakeClient()
    ship = Ship(views=views_path, client=cast("AsyncClient", client))
    ship._context._frontend = cast("Any", FakeProcess())
    ship._context._runtime_origin = "http://runtime.test"

    await ship._context._wait_for_health()

    assert client.get_calls == [("http://runtime.test/health", 0.2)]


async def test_widget_resource_renders_complete_document(views_path: Path):
    client = FakeClient()
    ship = Ship(
        views=views_path,
        client=cast("AsyncClient", client),
        metadata=Metadata(title="Base title"),
    )

    @ship.widget(path=Path("hello/widget.tsx"), name="hello", metadata=Metadata(description="Widget description"))
    def hello() -> None:
        return None

    ship._context._dev = True
    ship._context._runtime_origin = "http://render.test"

    html = await ship._widget_manager[Path("hello/widget.tsx")].resource.read()
    assert isinstance(html, str)

    assert client.calls == [("http://render.test/render", {"widget": "hello"})]
    assert "<title>Base title</title>" in html
    assert '<meta name="description" content="Widget description" />' in html
    assert '<meta name="robots" content="noindex" />' in html
    assert 'import RefreshRuntime from "http://render.test/@react-refresh"' in html
    assert "window.__vite_plugin_react_preamble_installed__ = true" in html
    assert '<div id="root"><main>Hello from production</main></div>' in html
    assert '<script type="module" src="http://render.test/@vite/client"></script>' in html
    assert '<script type="module" src="http://render.test/@gdansk/client/hello.tsx"></script>' in html


async def test_widget_resource_renders_production_scripts(views_path: Path):
    client = FakeClient()
    ship = Ship(
        views=views_path,
        client=cast("AsyncClient", client),
    )

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    ship._context._runtime_origin = "http://render.test"

    html = await ship._widget_manager[Path("hello/widget.tsx")].resource.read()
    assert isinstance(html, str)

    assert client.calls == [("http://render.test/render", {"widget": "hello"})]
    assert "@react-refresh" not in html
    assert "__vite_plugin_react_preamble_installed__" not in html
    assert '<script type="module" src="/dist/hello/client.js"></script>' in html
    assert "/@vite/client" not in html


async def test_widget_resource_uses_custom_assets_dir_for_production_scripts(views_path: Path):
    client = FakeClient()
    ship = Ship(
        views=views_path,
        assets="public",
        client=cast("AsyncClient", client),
    )

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    ship._context._runtime_origin = "http://render.test"

    html = await ship._widget_manager[Path("hello/widget.tsx")].resource.read()
    assert isinstance(html, str)

    assert client.calls == [("http://render.test/render", {"widget": "hello"})]
    assert '<script type="module" src="/public/hello/client.js"></script>' in html


async def test_widget_resource_uses_base_url_for_production_assets(views_path: Path):
    client = FakeClient()
    ship = Ship(
        views=views_path,
        base_url="https://example.com/app",
        client=cast("AsyncClient", client),
    )

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    ship._context._runtime_origin = "http://render.test"

    html = await ship._widget_manager[Path("hello/widget.tsx")].resource.read()
    assert isinstance(html, str)

    assert client.calls == [
        (
            "http://render.test/render",
            {"assetBaseUrl": "https://example.com/app/dist", "widget": "hello"},
        ),
    ]
    assert '<script type="module" src="https://example.com/app/dist/hello/client.js"></script>' in html


async def test_widget_resource_raises_on_invalid_render_payload(views_path: Path):
    client = FakeClient()
    client.render_payload = {"body": "<main>x</main>", "head": "not-a-list"}
    ship = Ship(
        views=views_path,
        client=cast("AsyncClient", client),
    )

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    ship._context._dev = True
    ship._context._runtime_origin = "http://render.test"

    with pytest.raises(TypeError, match="invalid render payload"):
        await ship._context.render_widget_page(metadata=None, widget_key="hello")


async def test_run_build_uses_the_views_vite_entrypoint(views_path: Path, monkeypatch: pytest.MonkeyPatch):
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

    ship = Ship(views=views_path)
    monkeypatch.setattr("gdansk.core.create_subprocess_exec", fake_create_subprocess_exec)

    await ship._context._run_build()

    assert captured_args == (
        ship._context._deno,
        "run",
        "-A",
        "--node-modules-dir=auto",
        "npm:vite",
        "build",
    )
    assert captured_kwargs is not None
    assert captured_kwargs["cwd"] == views_path
    assert "env" not in captured_kwargs


async def test_wait_for_health_timeout_mentions_matching_ship_and_plugin_config(
    views_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class UnreachableClient:
        async def get(self, url: str, **_kwargs: float | None) -> FakeResponse:
            msg = "connection failed"
            raise RequestError(msg, request=Request("GET", url))

    async def fake_sleep(_: float) -> None:
        return None

    ship = Ship(
        views=views_path,
        host="localhost",
        port=43123,
        client=cast("AsyncClient", UnreachableClient()),
    )
    ship._context._frontend = cast("Any", FakeProcess())
    ship._context._runtime_origin = "http://localhost:43123"
    monkeypatch.setattr("gdansk.core.sleep", fake_sleep)

    with pytest.raises(RuntimeError) as exc_info:
        await ship._context._wait_for_health()

    error = str(exc_info.value)
    assert 'Ensure Ship(host="localhost", port=43123)' in error
    assert 'gdansk({ host: "localhost", port: 43123 })' in error


async def test_ship_context_open_cleans_up_runtime_on_exit(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    process = FakeManagedProcess()
    ship = Ship(views=views_path)

    async def fake_create_subprocess_exec(*_args: str, **_kwargs: object) -> FakeManagedProcess:
        return process

    async def fake_wait_for_health() -> None:
        return None

    monkeypatch.setattr("gdansk.core.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(ship._context, "_wait_for_health", fake_wait_for_health)

    async with ship._context.open(dev=True):
        assert ship._context._active is True
        assert ship._context._dev is True
        assert ship._context._frontend is process
        assert ship._context._runtime_origin == "http://127.0.0.1:13714"

    assert process.terminated is True
    assert process.killed is False
    assert process.waited is False
    assert ship._context._active is False
    assert ship._context._dev is False
    assert ship._context._frontend is None
    assert ship._context._runtime_origin is None


async def test_ship_context_open_cleans_up_runtime_on_start_failure(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    process = FakeManagedProcess()
    ship = Ship(views=views_path)

    async def fake_create_subprocess_exec(*_args: str, **_kwargs: object) -> FakeManagedProcess:
        return process

    async def fake_wait_for_health() -> None:
        msg = "boom"
        raise RuntimeError(msg)

    monkeypatch.setattr("gdansk.core.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(ship._context, "_wait_for_health", fake_wait_for_health)

    with pytest.raises(RuntimeError, match="boom"):
        async with ship._context.open(dev=True):
            pytest.fail("ShipContext.open() should not yield after startup failure")

    assert process.terminated is True
    assert process.killed is False
    assert process.waited is False
    assert ship._context._active is False
    assert ship._context._dev is False
    assert ship._context._frontend is None
    assert ship._context._runtime_origin is None


async def test_ship_context_open_preserves_startup_error_when_runtime_exits_during_cleanup(
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

    async def fake_wait_for_health() -> None:
        msg = "boom"
        raise RuntimeError(msg)

    process = VanishedProcess()
    ship = Ship(views=views_path)
    monkeypatch.setattr("gdansk.core.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr("gdansk.core.sleep", fake_sleep)
    monkeypatch.setattr(ship._context, "_wait_for_health", fake_wait_for_health)

    with pytest.raises(RuntimeError, match="boom"):
        async with ship._context.open(dev=True):
            pytest.fail("ShipContext.open() should not yield after startup failure")

    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.wait_calls == 1
    assert ship._context._active is False
    assert ship._context._dev is False
    assert ship._context._frontend is None
    assert ship._context._runtime_origin is None


async def test_start_dev_uses_runtime_port(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    captured_args: tuple[str, ...] | None = None

    async def fake_create_subprocess_exec(*args: str, **_kwargs: object) -> FakeManagedProcess:
        nonlocal captured_args
        captured_args = args
        return FakeManagedProcess()

    async def fake_wait_for_health() -> None:
        return None

    ship = Ship(views=views_path, port=43123)
    monkeypatch.setattr("gdansk.core.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(ship._context, "_wait_for_health", fake_wait_for_health)

    await ship._context._start(dev=True)
    await ship._context._stop()

    assert captured_args == (
        ship._context._deno,
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


async def test_start_production_uses_server_entry(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    ship = Ship(views=views_path)
    captured_args: tuple[str, ...] | None = None
    wait_calls = 0

    async def fake_run_build() -> None:
        write_manifest(views_path)
        server_path = views_path / "dist" / "server.js"
        server_path.parent.mkdir(parents=True, exist_ok=True)
        server_path.write_text("console.log('server');\n", encoding="utf-8")

    async def fake_create_subprocess_exec(*args: str, **_kwargs: object) -> FakeManagedProcess:
        nonlocal captured_args
        captured_args = args
        return FakeManagedProcess()

    async def fake_wait_for_health() -> None:
        nonlocal wait_calls
        wait_calls += 1

    monkeypatch.setattr(ship._context, "_run_build", fake_run_build)
    monkeypatch.setattr(ship._context, "_wait_for_health", fake_wait_for_health)
    monkeypatch.setattr("gdansk.core.create_subprocess_exec", fake_create_subprocess_exec)

    await ship._context._start(dev=False)

    assert captured_args == (
        ship._context._deno,
        "run",
        "-A",
        "--node-modules-dir=auto",
        str(views_path / "dist" / "server.js"),
    )
    assert wait_calls == 1
    assert ship._context._runtime_origin == "http://127.0.0.1:13714"

    await ship._context._stop()


async def test_start_production_requires_server_entry(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    ship = Ship(views=views_path)

    async def fake_run_build() -> None:
        write_manifest(views_path)

    monkeypatch.setattr(ship._context, "_run_build", fake_run_build)

    with pytest.raises(RuntimeError, match="did not produce a production server entry"):
        await ship._context._start(dev=False)


async def test_ship_context_open_rejects_reentry(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    ship = Ship(views=views_path)
    calls: list[tuple[str, bool] | str] = []

    async def fake_start(*, dev: bool) -> None:
        calls.append(("start", dev))

    async def fake_stop() -> None:
        calls.append("stop")

    monkeypatch.setattr(ship._context, "_start", fake_start)
    monkeypatch.setattr(ship._context, "_stop", fake_stop)

    async with ship._context.open(dev=True):
        with pytest.raises(RuntimeError, match="already active"):
            async with ship._context.open(dev=False):
                pytest.fail("Nested ShipContext.open() should not yield")

    assert calls == [("start", True), "stop"]
    assert ship._context._active is False


def test_ship_widget_default_tool_and_resource_metadata(views_path: Path):
    ship = Ship(
        views=views_path,
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
        views=views_path,
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
        views=views_path,
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
        views=views_path,
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
        views=views_path,
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

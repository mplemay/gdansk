from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from gdansk.__tests__.unit.conftest import FakeManagedProcess, FakeProcess, write_manifest
from gdansk.core import Ship
from gdansk.manifest import GdanskManifest
from gdansk.metadata import Metadata
from gdansk.vite import Vite


async def test_wait_for_vite_reads_vite_client_endpoint(views_path: Path):
    requests_seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        ship = Ship(views=views_path, client=client)
        ship._context._vite._frontend = cast("Any", FakeProcess())
        ship._context._vite._origin = "http://runtime.test"

        await ship._context._vite.wait_for_client(client)

    assert len(requests_seen) == 1
    assert str(requests_seen[0].url) == "http://runtime.test/@vite/client"
    assert requests_seen[0].extensions.get("timeout") == {"connect": 0.2, "read": 0.2, "write": 0.2, "pool": 0.2}


async def test_widget_resource_renders_complete_document(views_path: Path):
    ship = Ship(
        views=views_path,
        metadata=Metadata(title="Base title"),
    )

    @ship.widget(path=Path("hello/widget.tsx"), name="hello", metadata=Metadata(description="Widget description"))
    def hello() -> None:
        return None

    ship._context._dev = True
    ship._context._vite._origin = "http://render.test"

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
    ship = Ship(views=views_path)

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    ship._context._manifest = ship._context._load_manifest()

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
    ship = Ship(views=views_path, assets="public")

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    ship._context._manifest = ship._context._load_manifest()

    html = await ship._widget_manager[Path("hello/widget.tsx")].resource.read()
    assert isinstance(html, str)

    assert '<link rel="stylesheet" href="/public/hello/client.css">' in html
    assert '<script type="module" src="/public/hello/client.js"></script>' in html


async def test_widget_resource_uses_base_url_for_production_assets(views_path: Path):
    write_manifest(views_path)
    ship = Ship(views=views_path, base_url="https://example.com/app")

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    ship._context._manifest = ship._context._load_manifest()

    html = await ship._widget_manager[Path("hello/widget.tsx")].resource.read()
    assert isinstance(html, str)

    assert '<link rel="stylesheet" href="https://example.com/app/dist/hello/client.css">' in html
    assert '<script type="module" src="https://example.com/app/dist/hello/client.js"></script>' in html


async def test_widget_resource_raises_when_manifest_is_missing_widget(views_path: Path):
    ship = Ship(views=views_path)

    @ship.widget(path=Path("hello/widget.tsx"), name="hello")
    def hello() -> None:
        return None

    ship._context._manifest = GdanskManifest(outDir="dist", root=str(views_path), widgets={})

    with pytest.raises(RuntimeError, match='does not contain the widget "hello"'):
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
    monkeypatch.setattr("gdansk.vite.create_subprocess_exec", fake_create_subprocess_exec)

    await ship._context._vite.run_build(views_path)

    assert captured_args == (
        ship._context._vite._deno,
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
            views=views_path,
            client=client,
            vite=Vite(host="localhost", port=43123),
        )
        ship._context._vite._frontend = cast("Any", FakeProcess())
        ship._context._vite._origin = "http://localhost:43123"
        monkeypatch.setattr("gdansk.vite.sleep", fake_sleep)

        with pytest.raises(RuntimeError) as exc_info:
            await ship._context._vite.wait_for_client(client)

    error = str(exc_info.value)
    assert 'Ensure Vite(host="localhost", port=43123)' in error
    assert 'gdansk({ host: "localhost", port: 43123 })' in error


async def test_ship_context_open_cleans_up_runtime_on_exit(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    process = FakeManagedProcess()
    ship = Ship(views=views_path)

    async def fake_create_subprocess_exec(*_args: str, **_kwargs: object) -> FakeManagedProcess:
        return process

    async def fake_wait_for_client(_client: httpx.AsyncClient) -> None:
        return None

    monkeypatch.setattr("gdansk.vite.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(ship._context._vite, "wait_for_client", fake_wait_for_client)

    async with ship._context.open(watch=True):
        assert ship._context._active is True
        assert ship._context._dev is True
        assert ship._context._vite._frontend is process
        assert ship._context._vite._origin == "http://127.0.0.1:13714"

    assert process.terminated is True
    assert process.killed is False
    assert process.waited is False
    assert ship._context._active is False
    assert ship._context._dev is False
    assert ship._context._vite._frontend is None
    assert ship._context._vite._origin is None
    assert ship._context._manifest is None


async def test_ship_context_open_cleans_up_runtime_on_start_failure(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    process = FakeManagedProcess()
    ship = Ship(views=views_path)

    async def fake_create_subprocess_exec(*_args: str, **_kwargs: object) -> FakeManagedProcess:
        return process

    async def fake_wait_for_client(_client: httpx.AsyncClient) -> None:
        msg = "boom"
        raise RuntimeError(msg)

    monkeypatch.setattr("gdansk.vite.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(ship._context._vite, "wait_for_client", fake_wait_for_client)

    with pytest.raises(RuntimeError, match="boom"):
        async with ship._context.open(watch=True):
            pytest.fail("ShipContext.open() should not yield after startup failure")

    assert process.terminated is True
    assert process.killed is False
    assert process.waited is False
    assert ship._context._active is False
    assert ship._context._dev is False
    assert ship._context._vite._frontend is None
    assert ship._context._vite._origin is None
    assert ship._context._manifest is None


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

    async def fake_wait_for_client(_client: httpx.AsyncClient) -> None:
        msg = "boom"
        raise RuntimeError(msg)

    process = VanishedProcess()
    ship = Ship(views=views_path)
    monkeypatch.setattr("gdansk.vite.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr("gdansk.vite.sleep", fake_sleep)
    monkeypatch.setattr(ship._context._vite, "wait_for_client", fake_wait_for_client)

    with pytest.raises(RuntimeError, match="boom"):
        async with ship._context.open(watch=True):
            pytest.fail("ShipContext.open() should not yield after startup failure")

    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.wait_calls == 1
    assert ship._context._active is False
    assert ship._context._dev is False
    assert ship._context._vite._frontend is None
    assert ship._context._vite._origin is None
    assert ship._context._manifest is None


async def test_start_dev_uses_runtime_port(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    captured_args: tuple[str, ...] | None = None

    async def fake_create_subprocess_exec(*args: str, **_kwargs: object) -> FakeManagedProcess:
        nonlocal captured_args
        captured_args = args
        return FakeManagedProcess()

    async def fake_wait_for_client(_client: httpx.AsyncClient) -> None:
        return None

    ship = Ship(views=views_path, vite=Vite(port=43123))
    monkeypatch.setattr("gdansk.vite.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(ship._context._vite, "wait_for_client", fake_wait_for_client)

    await ship._context._start(watch=True)
    await ship._context._stop()

    assert captured_args == (
        ship._context._vite._deno,
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
    ship = Ship(views=views_path)

    async def fake_run_build(_cwd: Path) -> None:
        write_manifest(views_path)

    monkeypatch.setattr(ship._context._vite, "run_build", fake_run_build)

    await ship._context._start(watch=False)

    assert ship._context._vite._frontend is None
    assert ship._context._manifest is not None
    assert ship._context._manifest.widgets["hello"].client == "dist/hello/client.js"
    assert ship._context._vite._origin is None

    await ship._context._stop()


async def test_start_production_requires_manifest(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    ship = Ship(views=views_path)

    async def fake_run_build(_cwd: Path) -> None:
        return None

    monkeypatch.setattr(ship._context._vite, "run_build", fake_run_build)

    with pytest.raises(RuntimeError, match="did not produce a manifest"):
        await ship._context._start(watch=False)


async def test_start_prebuilt_loads_manifest_without_build(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_manifest(views_path)
    ship = Ship(views=views_path)

    async def fail_run_build(_cwd: Path) -> None:
        pytest.fail("_run_build should not run when watch is None")

    monkeypatch.setattr(ship._context._vite, "run_build", fail_run_build)

    await ship._context._start(watch=None)

    assert ship._context._vite._frontend is None
    assert ship._context._manifest is not None
    assert ship._context._manifest.widgets["hello"].client == "dist/hello/client.js"
    assert ship._context._vite._origin is None
    assert ship._context._dev is False

    await ship._context._stop()


async def test_start_prebuilt_requires_manifest(views_path: Path):
    ship = Ship(views=views_path)

    with pytest.raises(RuntimeError, match="did not produce a manifest"):
        await ship._context._start(watch=None)


async def test_ship_context_open_prebuilt_skips_subprocess(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_manifest(views_path)
    ship = Ship(views=views_path)

    async def fail_create_subprocess_exec(*_args: str, **_kwargs: object) -> FakeManagedProcess:
        pytest.fail("create_subprocess_exec should not run when watch is None")

    monkeypatch.setattr("gdansk.vite.create_subprocess_exec", fail_create_subprocess_exec)

    async with ship._context.open(watch=None):
        assert ship._context._active is True
        assert ship._context._dev is False
        assert ship._context._vite._frontend is None
        assert ship._context._manifest is not None
        assert ship._context._vite._origin is None

    assert ship._context._active is False
    assert ship._context._manifest is None


def test_load_manifest_requires_matching_assets_directory(views_path: Path):
    write_manifest(views_path, assets_dir="public", manifest_out_dir="dist")
    ship = Ship(views=views_path, assets="public")

    with pytest.raises(RuntimeError, match="frontend build directory does not match"):
        ship._context._load_manifest()


async def test_ship_context_open_rejects_reentry(views_path: Path, monkeypatch: pytest.MonkeyPatch):
    ship = Ship(views=views_path)
    calls: list[tuple[str, bool | None] | str] = []

    async def fake_start(*, watch: bool | None) -> None:
        calls.append(("start", watch))

    async def fake_stop() -> None:
        calls.append("stop")

    monkeypatch.setattr(ship._context, "_start", fake_start)
    monkeypatch.setattr(ship._context, "_stop", fake_stop)

    async with ship._context.open(watch=True):
        with pytest.raises(RuntimeError, match="already active"):
            async with ship._context.open(watch=False):
                pytest.fail("Nested ShipContext.open() should not yield")

    assert calls == [("start", True), "stop"]
    assert ship._context._active is False

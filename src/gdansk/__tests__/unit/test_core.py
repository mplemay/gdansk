from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from gdansk.core import FrontendRuntime, RuntimeWidget, Ship
from gdansk.metadata import Metadata

if TYPE_CHECKING:
    from httpx import AsyncClient


class FakeResponse:
    def __init__(
        self,
        *,
        body: str = "",
        head: list[str] | None = None,
        payload: dict[str, Any] | None = None,
        status_code: int = 200,
    ) -> None:
        self._payload = payload if payload is not None else {"body": body, "head": head or []}
        self.status_code = status_code
        self.text = "ok"

    def json(self) -> dict[str, Any]:
        return cast("dict[str, Any]", self._payload)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.get_calls: list[tuple[str, float | None]] = []
        self.runtime_payload: dict[str, Any] = {
            "assetOrigin": "http://assets.test",
            "mode": "development",
            "ssrEndpoint": "/__gdansk_ssr",
            "ssrOrigin": "http://ssr.test",
            "viteOrigin": "http://vite.test",
            "widgets": {
                "hello": {"clientPath": "/.gdansk-src/hello/client.tsx"},
            },
        }

    async def get(self, url: str, **kwargs: float | None) -> FakeResponse:
        timeout = kwargs.get("timeout")
        self.get_calls.append((url, timeout))
        return FakeResponse(payload=self.runtime_payload)

    async def post(self, url: str, *, json: dict[str, str]) -> FakeResponse:
        self.calls.append((url, json))
        return FakeResponse(
            body="<main>Hello from SSR</main>",
            head=['<meta name="robots" content="noindex" />'],
        )


class FakeProcess:
    returncode: int | None = None


@pytest.fixture
def views_path(tmp_path: Path) -> Path:
    views = tmp_path / "views"
    (views / "widgets" / "hello").mkdir(parents=True)
    (views / "widgets" / "hello" / "widget.tsx").write_text("export default function App() { return null; }\n")
    return views


def test_widget_rejects_missing_widget_file(views_path: Path):
    ship = Ship(views=views_path)

    with pytest.raises(FileNotFoundError, match="is not a file"):
        ship.widget(path=Path("missing/widget.tsx"))


async def test_wait_for_runtime_reads_endpoint(views_path: Path):
    client = FakeClient()
    ship = Ship(views=views_path, client=cast("AsyncClient", client))
    ship._frontend = cast("Any", FakeProcess())
    ship._runtime_origin = "http://runtime.test"

    runtime = await ship._wait_for_runtime()

    assert client.get_calls == [("http://runtime.test/__gdansk_runtime", 0.2)]
    assert runtime.asset_origin == "http://assets.test"
    assert runtime.vite_origin == "http://vite.test"


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

    ship._runtime = FrontendRuntime(
        assetOrigin="http://assets.test",
        mode="development",
        ssrEndpoint="/__gdansk_ssr",
        ssrOrigin="http://ssr.test",
        viteOrigin="http://vite.test",
        widgets={
            "hello": RuntimeWidget(clientPath="/.gdansk-src/hello/client.tsx"),
        },
    )

    html = await ship._widget_manager[Path("hello/widget.tsx")].resource.read()
    assert isinstance(html, str)

    assert client.calls == [("http://ssr.test/__gdansk_ssr", {"widget": "hello"})]
    assert "<title>Base title</title>" in html
    assert '<meta name="description" content="Widget description" />' in html
    assert '<meta name="robots" content="noindex" />' in html
    assert '<div id="root"><main>Hello from SSR</main></div>' in html
    assert '<script type="module" src="http://vite.test/@vite/client"></script>' in html
    assert '<script type="module" src="http://assets.test/.gdansk-src/hello/client.tsx"></script>' in html


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

    await ship._run_build()

    assert captured_args == (
        "uv",
        "run",
        "deno",
        "run",
        "-A",
        "--node-modules-dir=auto",
        "npm:vite",
        "build",
    )
    assert captured_kwargs is not None
    assert captured_kwargs["cwd"] == views_path

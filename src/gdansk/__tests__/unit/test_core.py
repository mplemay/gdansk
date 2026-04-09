from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from gdansk.core import FrontendRuntime, RuntimeWidget, Ship
from gdansk.metadata import Metadata

if TYPE_CHECKING:
    from httpx import AsyncClient


class FakeResponse:
    def __init__(self, *, body: str, head: list[str], status_code: int = 200) -> None:
        self._payload = {"body": body, "head": head}
        self.status_code = status_code
        self.text = "ok"

    def json(self) -> dict[str, Any]:
        return cast("dict[str, Any]", self._payload)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def post(self, url: str, *, json: dict[str, str]) -> FakeResponse:
        self.calls.append((url, json))
        return FakeResponse(
            body="<main>Hello from SSR</main>",
            head=['<meta name="robots" content="noindex" />'],
        )


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
        asset_origin="http://assets.test",
        mode="development",
        ssr_endpoint="/__gdansk_ssr",
        ssr_origin="http://ssr.test",
        vite_origin="http://vite.test",
        widgets={
            "hello": RuntimeWidget(client_path="/.gdansk-src/hello/client.tsx"),
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

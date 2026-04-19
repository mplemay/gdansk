from __future__ import annotations

from pathlib import Path

import pytest
from mcp.server import MCPServer

from gdansk.__tests__.unit.conftest import write_manifest
from gdansk.core import Ship
from gdansk.metadata import Metadata
from gdansk.vite import Vite


@pytest.mark.integration
async def test_widget_resource_renders_through_mcp(views_path: Path):
    write_manifest(views_path)
    ship = Ship(vite=Vite(views_path), metadata=Metadata(title="Base title"))
    app = MCPServer(name="test")

    @ship.widget(
        path=Path("hello/widget.tsx"),
        name="hello",
        metadata=Metadata(description="Widget description"),
    )
    def hello() -> None:
        return None

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
        assert tool.meta["ui"]["resourceUri"] == resource.uri

        contents = list(await app.read_resource(resource.uri))
        assert len(contents) == 1
        content = contents[0]
        assert content.mime_type == resource.mime_type

        html = content.content
        assert isinstance(html, str)
        assert "<title>Base title</title>" in html
        assert '<meta name="description" content="Widget description" />' in html
        assert '<link rel="stylesheet" href="/dist/hello/client.css">' in html
        assert '<script type="module" src="/dist/hello/client.js"></script>' in html
        assert '<div id="root"></div>' in html

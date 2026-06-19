from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from gdansk.__tests__.conftest import mcp_mime_type, mcp_tool_input_schema, mcp_uri
from gdansk.__tests__.unit.conftest import write_manifest
from gdansk._mcp import MCPServer
from gdansk.core import Ship
from gdansk.metadata import Metadata
from gdansk.vite import Vite


class SearchFilters(BaseModel):
    city: str
    radius: int = 10


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
        resource = next((item for item in resources if mcp_uri(item) == "ui://hello"), None)
        assert resource is not None
        assert resource.name == "hello"
        assert mcp_mime_type(resource) == "text/html;profile=mcp-app"

        tools = await app.list_tools()
        tool = next((item for item in tools if item.name == "hello"), None)
        assert tool is not None
        assert tool.meta is not None
        assert tool.meta["ui"]["resourceUri"] == mcp_uri(resource)

        contents = list(await app.read_resource(mcp_uri(resource)))
        assert len(contents) == 1
        content = contents[0]
        assert mcp_mime_type(content) == mcp_mime_type(resource)

        html = content.content
        assert isinstance(html, str)
        assert "<title>Base title</title>" in html
        assert '<meta name="description" content="Widget description" />' in html
        assert "<style>.hello { color: red; }\n</style>" in html
        assert '<script type="module">console.log("hello");\n</script>' in html
        assert "/dist/hello/client.css" not in html
        assert "/dist/hello/client.js" not in html
        assert '<div id="root"></div>' in html


@pytest.mark.integration
async def test_widget_strict_schema_is_exposed_through_list_tools(views_path: Path):
    write_manifest(views_path)
    ship = Ship(vite=Vite(views_path))
    app = MCPServer(name="test")

    @ship.widget(
        path=Path("hello/widget.tsx"),
        name="hello",
        schema="strict",
    )
    def hello(filters: SearchFilters, name: str | None = None) -> None:
        _ = filters, name

    async with ship.mcp(app=app, watch=None):
        tools = await app.list_tools()
        tool = next((item for item in tools if item.name == "hello"), None)
        assert tool is not None

        input_schema = mcp_tool_input_schema(tool)
        assert input_schema["additionalProperties"] is False
        assert input_schema["required"] == ["filters", "name"]
        assert "default" not in input_schema["properties"]["name"]
        assert input_schema["$defs"]["SearchFilters"]["additionalProperties"] is False
        assert input_schema["$defs"]["SearchFilters"]["required"] == ["city", "radius"]

"""FastAPI integration example for Gdansk."""

import importlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server import MCPServer
from mcp.types import TextContent
from pydantic_settings import BaseSettings

from gdansk import Ship

FastAPI = importlib.import_module("fastapi").FastAPI


class Settings(BaseSettings):
    """Runtime settings for this example."""

    production: bool = False


SETTINGS = Settings()

ship = Ship(views=Path(__file__).parent / "src/mount/views")


@ship.widget(name="hello", path=Path("hello/widget.tsx"))
def hello(name: str = "world") -> list[TextContent]:
    """Return a greeting message."""
    return [TextContent(type="text", text=f"Hello, {name}!")]


@asynccontextmanager
async def mcp_lifespan(app: MCPServer) -> AsyncIterator[None]:
    async with ship.mcp(app=app, watch=not SETTINGS.production):
        yield


mcp = MCPServer(name="FastAPI Example Server", lifespan=mcp_lifespan)

mcp_app = mcp.streamable_http_app(streamable_http_path="/")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run the MCP app lifespan with the FastAPI app."""
    async with mcp_app.router.lifespan_context(mcp_app):
        yield


app = FastAPI(title="FastAPI + Gdansk Example", lifespan=lifespan)
app.mount(path="/dist", app=ship.assets)
app.mount(path="/mcp", app=mcp_app)

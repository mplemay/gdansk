"""FastAPI integration example for Gdansk."""

import importlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.types import TextContent
from pydantic_settings import BaseSettings

from gdansk import Amber

FastAPI = importlib.import_module("fastapi").FastAPI

try:
    FastMCP = importlib.import_module("mcp.server.fastmcp").FastMCP
except ImportError:
    FastMCP = importlib.import_module("mcp.server").MCPServer


class Settings(BaseSettings):
    """Runtime settings for this example."""

    production: bool = False


SETTINGS = Settings()

mcp = FastMCP("FastAPI Example Server", streamable_http_path="/")
amber = Amber(mcp=mcp, views=Path(__file__).parent / "src/mount/views")


@amber.tool(name="hello", widget=Path("hello"))
def hello(name: str = "world") -> list[TextContent]:
    """Return a greeting message."""
    return [TextContent(type="text", text=f"Hello, {name}!")]


mcp_app = amber(dev=not SETTINGS.production)


@asynccontextmanager
async def lifespan(_: object) -> AsyncIterator[None]:
    """Run the MCP app lifespan with the FastAPI app."""
    async with mcp_app.router.lifespan_context(mcp_app):
        yield


app = FastAPI(title="FastAPI + Gdansk Example", lifespan=lifespan)
app.mount(path="/mcp", app=mcp_app)

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
from pydantic_settings import BaseSettings

from fastapi import FastAPI
from gdansk import Amber


class Settings(BaseSettings):
    production: bool = False


SETTINGS = Settings()

mcp = FastMCP("FastAPI Example Server", streamable_http_path="/")
amber = Amber(mcp=mcp, views=Path(__file__).parent / "src/mount/views")


@amber.tool(name="hello", ui=Path("hello/app.tsx"))
def hello(name: str = "world") -> list[TextContent]:
    return [TextContent(type="text", text=f"Hello, {name}!")]


mcp_app = amber(dev=not SETTINGS.production)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with mcp_app.router.lifespan_context(mcp_app):
        yield


app = FastAPI(title="FastAPI + Gdansk Example", lifespan=lifespan)
app.mount(path="/mcp", app=mcp_app)

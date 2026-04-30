"""Get Time MCP Server — returns the current time."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from mcp.server import MCPServer
from mcp.types import TextContent
from starlette.middleware.cors import CORSMiddleware

from gdansk import Ship, Vite

ship = Ship(vite=Vite(Path(__file__).parent / "views"))


@ship.widget(name="get-time", path=Path("get-time/widget.tsx"))
def get_time() -> list[TextContent]:
    """Get the current server time in ISO 8601 format."""
    time_str = datetime.now(tz=UTC).isoformat()
    return [TextContent(type="text", text=time_str)]


@asynccontextmanager
async def lifespan(mcp: MCPServer) -> AsyncIterator[None]:  # noqa: D103
    async with ship.lifespan(app=mcp, watch=True):
        yield


mcp = MCPServer(name="Get Time Server", lifespan=lifespan)


def main() -> None:
    """Run the development server for the get-time example."""
    app = mcp.streamable_http_app()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount(path=ship.assets_path, app=ship.assets)
    uvicorn.run(app, port=3001)


if __name__ == "__main__":
    main()

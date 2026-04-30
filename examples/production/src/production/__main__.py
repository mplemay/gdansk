"""Production example server."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from mcp.server import MCPServer
from mcp.types import TextContent
from starlette.middleware.cors import CORSMiddleware

from gdansk import Ship, Vite

ship = Ship(vite=Vite(Path(__file__).parent / "views"))


@ship.widget(name="hello", path=Path("hello/widget.tsx"))
def hello() -> list[TextContent]:
    """Return a static greeting rendered from the production example."""
    return [TextContent(type="text", text="Hello from the production example")]


@asynccontextmanager
async def lifespan(mcp: MCPServer) -> AsyncIterator[None]:  # noqa: D103
    async with ship.lifespan(app=mcp, watch=False):
        yield


mcp = MCPServer(name="Production Example Server", lifespan=lifespan)


def main() -> None:
    """Run the production example server."""
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

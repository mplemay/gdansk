"""Server-side rendering example server."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from mcp.server import MCPServer
from mcp.types import TextContent
from starlette.middleware.cors import CORSMiddleware

from gdansk import Ship

ship = Ship(views=Path(__file__).parent / "views")


@ship.widget(name="hello-ssr", path=Path("hello-ssr/widget.tsx"))
def hello_ssr() -> list[TextContent]:
    """Return a static greeting rendered from the SSR example."""
    return [TextContent(type="text", text="Hello from the SSR example")]


@asynccontextmanager
async def lifespan(app: MCPServer) -> AsyncIterator[None]:  # noqa: D103
    async with ship.mcp(app=app, dev=True):
        yield


mcp = MCPServer(name="SSR Example Server", lifespan=lifespan)


def main() -> None:
    """Run the development server for the SSR example."""
    app = mcp.streamable_http_app()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount(path="/assets", app=ship.assets)
    uvicorn.run(app, port=3001)


if __name__ == "__main__":
    main()

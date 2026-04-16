from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from mcp.server import MCPServer
from mcp.types import TextContent
from starlette.middleware.cors import CORSMiddleware

from gdansk import Ship

ship = Ship(views=Path(__file__).parent / "views")


@ship.widget(name="hello", path=Path("hello/widget.tsx"))
def hello() -> list[TextContent]:
    """Return a static greeting rendered from the production example."""
    return [TextContent(type="text", text="Hello from the production example")]


@asynccontextmanager
async def lifespan(app: MCPServer) -> AsyncIterator[None]:
    async with ship.mcp(app=app, dev=True) as context:
        yield context


mcp = MCPServer(name="example", lifespan=lifespan)


def main() -> None:
    """Run the development server for the production example."""
    app = mcp.streamable_http_app()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount(path="/dist", app=ship.assets)
    uvicorn.run(app, port=3001)


if __name__ == "__main__":
    main()

"""Get Time MCP Server — returns the current time."""

import importlib
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from mcp.types import TextContent
from starlette.middleware.cors import CORSMiddleware

from gdansk import Amber

try:
    FastMCP = importlib.import_module("mcp.server.fastmcp").FastMCP
except ImportError:
    FastMCP = importlib.import_module("mcp.server").MCPServer

mcp = FastMCP("Get Time Server")
amber = Amber(mcp=mcp, views=Path(__file__).parent / "views")


@amber.tool(name="get-time", widget=Path("get-time"))
def get_time() -> list[TextContent]:
    """Get the current server time in ISO 8601 format."""
    time_str = datetime.now(tz=UTC).isoformat()
    return [TextContent(type="text", text=time_str)]


def main() -> None:
    """Run the development server for the get-time example."""
    app = amber(dev=True)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    uvicorn.run(app, port=3001)


if __name__ == "__main__":
    main()

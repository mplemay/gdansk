"""Get Time MCP Server — returns the current time."""

from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
from starlette.middleware.cors import CORSMiddleware

from gdansk import Amber

mcp = FastMCP("Get Time Server")
amber = Amber(mcp=mcp, views=Path(__file__).parent / "views")


@amber.tool(name="get-time", ui=Path("get-time/app.tsx"))
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

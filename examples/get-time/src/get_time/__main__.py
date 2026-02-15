"""Get Time MCP Server — returns the current time."""

from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from mcp import types
from mcp.server.fastmcp import FastMCP
from starlette.middleware.cors import CORSMiddleware

from gdansk import Amber

mcp = FastMCP("Get Time Server", stateless_http=True)
amber = Amber(mcp=mcp, dev=True)


@amber.tool(ui=Path("page.tsx"))
def get_time() -> list[types.TextContent]:
    """Get the current server time in ISO 8601 format."""
    time_str = datetime.now(tz=UTC).isoformat()
    return [types.TextContent(type="text", text=time_str)]


def main() -> None:
    app = mcp.streamable_http_app()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    print("Get Time Server listening on http://0.0.0.0:3001/mcp")
    uvicorn.run(app, host="0.0.0.0", port=3001)


if __name__ == "__main__":
    main()

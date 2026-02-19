from pathlib import Path

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
from starlette.middleware.cors import CORSMiddleware

from gdansk import Amber

mcp = FastMCP("SSR Example Server")
amber = Amber(mcp=mcp, views=Path(__file__).parent / "views", ssr=True)


@amber.tool(name="hello-ssr", ui=Path("hello-ssr/app.tsx"))
def hello_ssr() -> list[TextContent]:
    return [TextContent(type="text", text="Hello from the SSR example")]


def main() -> None:
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

# Quickstart

Use this file for a minimal, working gdansk setup before adding complexity.

## Canonical layout

```text
my-server/
├── server.py
└── views/
    ├── package.json
    └── apps/
        └── hello/
            └── page.tsx
```

## Minimal Python server

```python
from pathlib import Path

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from gdansk import Amber

mcp = FastMCP("Hello Server")
amber = Amber(mcp=mcp, views=Path(__file__).parent / "views")


@amber.tool(name="hello", page=Path("hello"))
def hello(name: str = "world") -> list[TextContent]:
    return [TextContent(type="text", text=f"Hello, {name}!")]


if __name__ == "__main__":
    app = amber(dev=True)
    uvicorn.run(app, port=3001)
```

## Minimal React page

`views/apps/hello/page.tsx`

```tsx
import { useApp } from "@modelcontextprotocol/ext-apps/react";

export default function App() {
  const { app, error } = useApp({
    appInfo: { name: "Hello", version: "1.0.0" },
    capabilities: {},
  });

  if (error) return <div>Error: {error.message}</div>;
  if (!app) return <div>Connecting...</div>;

  return (
    <main>
      <h2>Hello</h2>
      <button
        onClick={async () => {
          await app.callServerTool({
            name: "hello",
            arguments: { name: "from MCP UI" },
          });
        }}
      >
        Call hello
      </button>
    </main>
  );
}
```

## Baseline views package.json

`views/package.json`

```json
{
  "name": "gdansk-views",
  "private": true,
  "type": "module",
  "dependencies": {
    "@modelcontextprotocol/ext-apps": "^1.0.1",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0"
  }
}
```

## Run commands

Standard server:

```bash
uv sync
uv run python server.py
```

SSR variant:

```python
amber = Amber(mcp=mcp, views=Path(__file__).parent / "views", ssr=True)
```

Run:

```bash
uv sync
uv run python server.py
```

FastAPI mount pattern:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from gdansk import Amber

mcp = FastMCP("FastAPI Example Server", streamable_http_path="/")
amber = Amber(mcp=mcp, views=Path(__file__).parent / "views")

@amber.tool(name="hello", page=Path("hello"))
def hello(name: str = "world") -> list[TextContent]:
    return [TextContent(type="text", text=f"Hello, {name}!")]

mcp_app = amber(dev=True)

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with mcp_app.router.lifespan_context(mcp_app):
        yield

app = FastAPI(lifespan=lifespan)
app.mount(path="/mcp", app=mcp_app)
```

Run:

```bash
uv sync
uv run fastapi dev main.py
```

## Quick checks

After startup, confirm bundle output exists:

```bash
find views/.gdansk -maxdepth 3 -type f
```

Expected for non-SSR hello:

- `views/.gdansk/hello/client.js`
- optional `views/.gdansk/hello/client.css`

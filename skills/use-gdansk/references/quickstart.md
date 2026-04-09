# Quickstart

Use this file for a minimal, working gdansk setup before adding complexity.

## Canonical layout

```text
my-server/
├── server.py
└── views/
    ├── package.json
    ├── deno.lock
    └── widgets/
        └── hello/
            └── widget.tsx
```

The `views` directory name is arbitrary: `Ship(..., views=...)` accepts any path to the package root (the directory that
contains `package.json`).

## Minimal Python server

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from mcp.server import MCPServer
from mcp.types import TextContent
from starlette.middleware.cors import CORSMiddleware

from gdansk import Ship

ship = Ship(views=Path(__file__).parent / "views")


@ship.widget(path=Path("hello/widget.tsx"), name="hello")
def hello(name: str = "world") -> list[TextContent]:
    return [TextContent(type="text", text=f"Hello, {name}!")]


@asynccontextmanager
async def lifespan(app: MCPServer) -> AsyncIterator[None]:
    async with ship.mcp(app=app, dev=True):
        yield


mcp = MCPServer(name="Hello Server", lifespan=lifespan)


if __name__ == "__main__":
    app = mcp.streamable_http_app()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    uvicorn.run(app, port=3001)
```

## Minimal React widget

`views/widgets/hello/widget.tsx`

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

After editing dependencies, install from `views/` with `uv run deno install` and commit `deno.lock` when it changes:

```bash
cd views
uv run deno install
```

## Run commands

Standard server:

```bash
uv sync
( cd views && uv run deno install )
uv run python server.py
```

FastAPI mount pattern:

```python
import importlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server import MCPServer
from mcp.types import TextContent

from gdansk import Ship

FastAPI = importlib.import_module("fastapi").FastAPI

ship = Ship(views=Path(__file__).parent / "views")


@ship.widget(path=Path("hello/widget.tsx"), name="hello")
def hello(name: str = "world") -> list[TextContent]:
    return [TextContent(type="text", text=f"Hello, {name}!")]


@asynccontextmanager
async def mcp_lifespan(app: MCPServer) -> AsyncIterator[None]:
    async with ship.mcp(app=app, dev=True):
        yield


mcp = MCPServer(name="FastAPI Example Server", lifespan=mcp_lifespan)
mcp_app = mcp.streamable_http_app(streamable_http_path="/")


@asynccontextmanager
async def lifespan(_: object) -> AsyncIterator[None]:
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

Expected for a basic hello widget:

- `views/.gdansk/hello/client.js`
- `views/.gdansk/hello/server.js`
- optional `views/.gdansk/hello/client.css`

# Quickstart

Use this file for a minimal, working gdansk setup before adding complexity.

## Canonical layout

```text
my-server/
├── server.py
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── deno.lock
    └── widgets/
        └── hello/
            └── widget.tsx
```

The `frontend` directory name is arbitrary: `Ship(..., views=...)` accepts any path to the package root (the directory
that contains `package.json`).

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

frontend_path = Path(__file__).parent / "frontend"
ship = Ship(views=frontend_path)


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
    app.mount(path="/dist", app=ship.assets)
    uvicorn.run(app, port=3001)
```

Production widgets load hydration assets from `/<assets_dir>/...`, so mount `ship.assets` at that path on the public
app. With the default settings, mount it at `/dist`.

Default production output:

- `frontend/dist/manifest.json`
- `frontend/dist/gdansk-manifest.json`
- `frontend/dist/hello/client.js`
- optional `frontend/dist/hello/client.css`
- `frontend/dist/assets/*`
- `frontend/dist/server.js`

## Minimal React widget

`frontend/widgets/hello/widget.tsx`

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

## Baseline frontend package.json

`frontend/package.json`

```json
{
  "name": "gdansk-frontend",
  "private": true,
  "type": "module",
  "dependencies": {
    "@gdansk/vite": "^0.1.0",
    "@modelcontextprotocol/ext-apps": "^1.5.0",
    "@vitejs/plugin-react": "^6.0.1",
    "react": "^19.2.5",
    "react-dom": "^19.2.5",
    "vite": "^8.0.8"
  },
  "devDependencies": {
    "@types/react": "^19.2.14",
    "@types/react-dom": "^19.2.3"
  }
}
```

Add a `vite.config.ts` in the same package and import `@gdansk/vite` there alongside any framework plugins:

`frontend/vite.config.ts`

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import gdansk from "@gdansk/vite";

export default defineConfig({
  plugins: [gdansk(), react()],
});
```

If you need a non-default SSR address, set it on both sides:

```python
ship = Ship(views=Path(__file__).parent / "frontend", host="127.0.0.1", port=14000)
```

```ts
export default defineConfig({
  plugins: [gdansk({ host: "127.0.0.1", port: 14000 }), react()],
});
```

After editing dependencies, install from `frontend/` with `uv run deno install` and commit `deno.lock` when it
changes:

```bash
cd frontend
uv run deno install
```

## Run commands

Standard server:

```bash
uv sync
( cd frontend && uv run deno install )
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

ship = Ship(views=Path(__file__).parent / "frontend")


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
app.mount(path="/dist", app=ship.assets)
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
find frontend/dist -maxdepth 3 -type f
```

Expected for a basic hello widget:

- `frontend/dist/hello/client.js`
- `frontend/dist/server.js`
- optional `frontend/dist/hello/client.css`

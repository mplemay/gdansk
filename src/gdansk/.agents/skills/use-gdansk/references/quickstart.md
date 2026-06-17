# Quickstart

Use this file for a minimal, working gdansk setup before adding complexity.

## Path A: `gdansk init` (recommended)

Scaffold a new project with the CLI:

```bash
uv add gdansk
uv run gdansk init
uv run gdansk install
uv run gdansk doctor
```

`gdansk init` creates:

```text
my-server/
├── pyproject.toml
└── src/<package>/
    ├── __main__.py
    └── views/                  # CLI default frontend root name
        ├── vite.config.ts
        └── widgets/
            └── hello/
                └── widget.tsx
```

Run the scaffolded server:

```bash
uv run python -m <package>
```

For CLI details, see [cli.md](cli.md).

## Path B: manual layout

Use this when adding gdansk to an existing repo or when you prefer a custom directory name.

```text
my-server/
├── server.py
├── pyproject.toml
└── frontend/                   # name is arbitrary; pass any path to Vite(...)
    ├── vite.config.ts
    ├── deno.lock                 # belgie lockfile at Python project root
    └── widgets/
        └── hello/
            └── widget.tsx
```

The frontend directory name is arbitrary: `Vite(...)` accepts any path containing `vite.config.ts` and `widgets/`.
`gdansk init` uses `views/` by default; manual setups often use `frontend/`.

## Minimal Python server

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from mcp.server import MCPServer
from mcp.types import TextContent
from starlette.middleware.cors import CORSMiddleware

from gdansk import Ship, Vite

frontend_path = Path(__file__).parent / "views"  # or "frontend" for manual layout
ship = Ship(vite=Vite(frontend_path))


@ship.widget(path=Path("hello/widget.tsx"), name="hello")
def hello(name: str = "world") -> list[TextContent]:
    return [TextContent(type="text", text=f"Hello, {name}!")]


@asynccontextmanager
async def lifespan(app: MCPServer) -> AsyncIterator[None]:
    async with ship.mcp(app=app, watch=True):
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

Production widget resources are self-contained HTML. The generated page includes inline CSS and a single inline module
script, so the HTTP app only needs to expose the MCP app.

Default production output is:

- `<frontend-root>/dist/gdansk-manifest.json`

## Minimal React widget

`<frontend-root>/widgets/hello/widget.tsx`

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

For richer widget patterns, see [widgets.md](widgets.md).

## Baseline pyproject.toml frontend dependencies

`pyproject.toml`

```toml
[belgie.dependencies]
vite = "8.0.8"
"@gdansk/vite" = "^0.1.0"
"@modelcontextprotocol/ext-apps" = "^1.5.0"
"@vitejs/plugin-react" = "6.0.2"
react = "19.2.6"
react-dom = "19.2.6"

[belgie.dependencies.dev]
"@types/react" = "^19.2.14"
"@types/react-dom" = "^19.2.3"

[belgie.scripts]
build = "vite build"
dev = "vite"
```

Add a `vite.config.ts` in the frontend root and import `@gdansk/vite` there alongside any framework plugins:

`<frontend-root>/vite.config.ts`

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import gdansk from "@gdansk/vite";

export default defineConfig({
  plugins: [gdansk({ refresh: true }), react()],
});
```

`@gdansk/vite` provides a default `@` alias to the frontend root, so you only need a manual `@` alias if the
repo wants `@` to resolve somewhere else. `refresh: true` adds Laravel-style full reloads for nearby Python and Jinja
files during `vite dev`.

If you need a non-default build output directory, keep Python and Vite aligned. See
[rules/config-sync.md](../rules/config-sync.md) for Incorrect/Correct pairs.

After editing dependencies, install from the Python project root:

```bash
uv run gdansk install
```

Commit the belgie lockfile (`deno.lock`) when it changes.

## Run commands

Standard server:

```bash
uv sync
uv run gdansk install
uv run gdansk doctor
uv run python server.py          # manual layout
# or
uv run python -m <package>       # gdansk init layout
```

For FastAPI mounting, see [integrations.md](integrations.md).
For production deployment, see [production.md](production.md).

## Quick checks

After startup, confirm the inline manifest exists:

```bash
find <frontend-root>/dist -maxdepth 3 -type f
```

Expected for a basic hello widget: `<frontend-root>/dist/gdansk-manifest.json`.

If checks fail, run `uv run gdansk doctor` then see [troubleshooting.md](troubleshooting.md).

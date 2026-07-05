---
name: use-gdansk
description: >-
  Build and debug gdansk MCP widget apps using Ship, Vite, @gdansk/widget, isolated React widget descriptors,
  gdansk dependencies, metadata, structured output, and FastAPI mounting.
license: MIT
compatibility: Requires Python >=3.12,<3.15, Belgie >=0.31.0, and Vite >=8.1,<9
allowed-tools: Bash(uv run gdansk *)
metadata:
  version: "2.0.0"
  author: gdansk
---

# Use Gdansk

Gdansk connects Python MCP tools to isolated React widget modules through `Ship`, `Vite`, and `@gdansk/widget`.
Use only gdansk's public integration surface.

## Core contract

1. Run `uv run gdansk init`, then `uv run gdansk lock` and `uv run gdansk doctor`.
2. Pass the frontend root containing `widgets/` to `Vite(...)`.
3. Register `path=Path("<name>/widget.tsx")` relative to `widgets/`.
4. Default-export a function that returns `render({ widget: <Component /> })`.
5. Keep HTML metadata in the TypeScript descriptor and MCP metadata on `@ship.widget(...)`.
6. Declare packages in `[gdansk.dependencies]`; do not create app-level `package.json`, `deno.json`, or
   `vite.config.ts` files.
7. Run frontend tasks through `uv run gdansk build` and `uv run gdansk dev`.

## Minimal server

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server import MCPServer
from mcp.types import TextContent

from gdansk import Ship, Vite

ship = Ship(vite=Vite(Path(__file__).parent / "views"))


@ship.widget(path=Path("hello/widget.tsx"), name="hello")
def hello(name: str = "world") -> list[TextContent]:
    return [TextContent(type="text", text=f"Hello, {name}!")]


@asynccontextmanager
async def lifespan(app: MCPServer) -> AsyncIterator[None]:
    async with ship.mcp(app=app, watch=True):
        yield


mcp = MCPServer(name="Hello server", lifespan=lifespan)
```

## Minimal widget

```tsx
import { render } from "@gdansk/widget";

function Hello() {
  return <main>Hello</main>;
}

export default function widget() {
  return render({
    metadata: { title: "Hello", description: "A hello widget" },
    widget: <Hello />,
  });
}
```

For a Vite plugin, use a server-only reference:

```tsx
import { render, vitePlugin } from "@gdansk/widget";

export default function widget() {
  return render({
    plugins: [vitePlugin("@tailwindcss/vite")],
    widget: <main className="p-4">Hello</main>,
  });
}
```

Never statically import a Vite plugin from a widget. `vitePlugin(specifier, { export?, args? })` resolves it only in
the Deno build/dev process and keeps Node/native dependencies out of the browser bundle.

## Watch modes

- `watch=True`: one isolated Vite dev server per widget, with HMR and React Refresh.
- `watch=False`: build on startup and serve complete HTML from `gdansk-manifest.json`.
- `watch=None`: serve an existing production manifest without starting frontend tooling.

Production widget HTML is self-contained. Do not mount or expect separate widget JS/CSS assets.

## Reference routing

| Need | Reference |
| --- | --- |
| Copy a complete setup | [references/quickstart.md](references/quickstart.md) |
| Understand paths | [references/path-contract.md](references/path-contract.md) |
| Build widget UI | [references/widgets.md](references/widgets.md) |
| Configure metadata, Tailwind, or FastAPI | [references/integrations.md](references/integrations.md) |
| Understand runtime and watch modes | [references/architecture.md](references/architecture.md) |
| Deploy prebuilt widgets | [references/production.md](references/production.md) |
| Use CLI commands | [references/cli.md](references/cli.md) |
| Diagnose failures | [references/troubleshooting.md](references/troubleshooting.md) |

## Failure order

1. Run `uv run gdansk doctor`.
2. Confirm the frontend root and `widgets/<name>/widget.tsx` path.
3. Confirm the default export returns `render({...})`.
4. Confirm packages and plugin references are declared in `[gdansk.dependencies]`, then run `uv run gdansk lock`.
5. Inspect `dist/gdansk-manifest.json` for production or the temporary dev-manifest error for development.
6. Confirm the Python tool name matches `callServerTool({ name: ... })`.

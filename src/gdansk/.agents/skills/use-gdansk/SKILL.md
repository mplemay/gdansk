---
name: use-gdansk
description: Build and debug gdansk MCP widget apps — Ship/Vite wiring, React widgets, belgie deps, metadata, structured output, FastAPI mounting, and error-driven troubleshooting. Use when the user mentions gdansk, Ship, @gdansk/vite, @ship.widget, MCP UI widgets, or broken widget bundling/render.
license: MIT
compatibility: Requires Python >=3.12,<3.15
metadata:
  version: "1.0.0"
  author: gdansk
---

# Use Gdansk

Gdansk connects React widget UIs to Python MCP servers through `Ship`, `Vite`, and `@gdansk/vite`.
This skill covers adoption, extension, and troubleshooting using only gdansk's public API.

## When to Use This Skill

Invoke this skill when:

- Bootstrapping gdansk in a new repo or adding widgets to an existing integration
- Wiring `ship.mcp(app=...)` with `MCPServer`, `@ship.widget(...)`, and `@gdansk/vite`
- Adding metadata, structured output, FastAPI mounting, or plain `@mcp.tool` tools
- Diagnosing widget registration, bundling, render, host/port, or path contract failures
- Code imports `gdansk`, `Ship`, or `Vite`

Do **not** use this skill for:

- Generic React or MCP server work without gdansk
- Inspecting gdansk internals when the public API or emitted error already explains the task

## Quick-Start Patterns

### Minimal Python server

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server import MCPServer
from mcp.types import TextContent

from gdansk import Ship, Vite

frontend_path = Path(__file__).parent / "frontend"
ship = Ship(vite=Vite(frontend_path))


@ship.widget(path=Path("hello/widget.tsx"), name="hello")
def hello(name: str = "world") -> list[TextContent]:
    return [TextContent(type="text", text=f"Hello, {name}!")]


@asynccontextmanager
async def lifespan(app: MCPServer) -> AsyncIterator[None]:
    async with ship.mcp(app=app, watch=True):
        yield


mcp = MCPServer(name="Hello Server", lifespan=lifespan)
```

Mount `ship.assets` at `ship.assets_path` on the public HTTP app (default `/dist`).

### Minimal React widget

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

  return <main><h2>Hello</h2></main>;
}
```

### Minimal Vite config

`frontend/vite.config.ts`

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import gdansk from "@gdansk/vite";

export default defineConfig({
  plugins: [gdansk({ refresh: true }), react()],
});
```

## Classify the Request

Choose one primary path before making edits:

1. **Bootstrap gdansk in a new repo** — dependency, frontend root, first widget, server lifespan.
2. **Add another widget** — tool function, `widgets/<name>/widget.tsx`, `@ship.widget(path=Path("..."))`.
3. **Extend integration** — metadata, `structured_output=True`, extra `@mcp.tool` tools, FastAPI mounting.
4. **Debug broken integration** — classify the failing boundary, then load
   [TROUBLESHOOTING.md](references/TROUBLESHOOTING.md).

After implementation or each fix, verify startup, bundle output under `dist/`, rendered HTML scripts, and tool calls.

## Task Routing Table

Load only the most relevant reference first. Read additional references only if the task spans multiple areas.

| I want to… | Reference |
| --- | --- |
| Bootstrap or copy minimal working layout | [QUICKSTART.md](references/QUICKSTART.md) |
| Check compatibility, deps, verification checklist | [ADOPTION.md](references/ADOPTION.md) |
| Metadata, structured output, FastAPI, plain tools, styling | [INTEGRATIONS.md](references/INTEGRATIONS.md) |
| Validate `@ship.widget(path=...)` inputs | [PATH-CONTRACT.md](references/PATH-CONTRACT.md) |
| Fix errors / missing bundles / render failures | [TROUBLESHOOTING.md](references/TROUBLESHOOTING.md) |

## Key Practices

- Use the public integration surface: `Ship`, `Vite`, `@ship.widget(...)`, `ship.mcp(...)`, `@gdansk/vite`.
- Pass the frontend root to `Vite(...)`, not the `widgets/` directory.
- Register widgets with `path=Path("<dir>/widget.tsx")` relative to `widgets/` inside the frontend root.
- Keep `Vite(Path(...), host=..., port=..., build_directory=...)` aligned with matching `gdansk({...})` options.
- After changing `[belgie.dependencies]`, run `uv run gdansk install` from the Python project root.
- Prefer `gdansk({ refresh: true })` when nearby Python or Jinja edits should reload the browser during development.
- Mount `ship.assets` at `ship.assets_path` for production hydration assets.

## Common Gotchas

- Do not prefix `@ship.widget(path=...)` with `widgets/` or pass absolute paths.
- Widget entry files must be named `widget.tsx` or `widget.jsx` and default-export the React component.
- Do not invent alternative entry conventions such as `app.tsx`.
- Duplicate widget paths raise `The widget ... has already been registered`; duplicate tool names raise
  `A tool with the name ... has already been registered`.
- Host, port, and `buildDirectory` must match on both Python (`Vite(...)`) and Vite (`gdansk({...})`) sides.
- If startup, bundling, or rendering fails after wiring, switch to the troubleshooting reference instead of
  rewriting the integration architecture.

---
name: use-gdansk
description: >-
  Build and debug gdansk MCP widget apps — Ship/Vite wiring, React widgets, gdansk dependencies, gdansk init,
  gdansk doctor, gdansk lock, metadata, structured output, FastAPI mounting, and error-driven
  troubleshooting. Use when the user mentions gdansk, Ship, @gdansk/vite, @ship.widget, MCP UI widgets,
  gdansk.dependencies, or broken widget bundling/render.
license: MIT
compatibility: Requires Python >=3.12,<3.15
allowed-tools: Bash(uv run gdansk *)
metadata:
  version: "1.1.0"
  author: gdansk
---

# Use Gdansk

Gdansk connects React widget UIs to Python MCP servers through `Ship`, `Vite`, and `@gdansk/vite`.
This skill covers adoption, extension, and troubleshooting using only gdansk's public API.

## When to Use This Skill

Invoke this skill when:

- Bootstrapping gdansk in a new repo or adding widgets to an existing integration
- Running `gdansk init`, `gdansk lock`, `gdansk doctor`, `gdansk build`, or `gdansk dev`
- Wiring `ship.mcp(app=...)` with `MCPServer`, `@ship.widget(...)`, and `@gdansk/vite`
- Adding metadata, structured output, FastAPI mounting, or plain `@mcp.tool` tools
- Diagnosing widget registration, bundling, render, host/port, or path contract failures
- Code imports `gdansk`, `Ship`, or `Vite`

Do **not** use this skill for:

- Generic React or MCP server work without gdansk
- Inspecting gdansk internals when the public API or emitted error already explains the task

## Principles

1. Use `gdansk init` + `gdansk doctor` before hand-rolling project layout.
2. One widget = one Python tool + one `widget.tsx` + one `ui://` resource.
3. Keep Python `Vite(...)` and `gdansk({...})` config in sync; diagnose from the failing boundary outward.
4. Use inline patterns in skill references rather than inventing architecture.

## Critical Rules

These rules are **always enforced**. Each links to Incorrect/Correct pairs.

### Widget path contract → [rules/path-contract.md](rules/path-contract.md)

- Pass `path=Path("<dir>/widget.tsx")` relative to `widgets/`, never prefixed with `widgets/`.
- Entry files must be named `widget.tsx` or `widget.jsx` and default-export the React component.

### Config sync → [rules/config-sync.md](rules/config-sync.md)

- `Vite(host, port, build_directory)` must match `gdansk({ host, port, buildDirectory })`.
- Pass the frontend root to `Vite(...)`, not the `widgets/` directory.

### Widget wiring → [rules/widget-wiring.md](rules/widget-wiring.md)

- Python tool `name` must match `callServerTool({ name: ... })` in the React widget.
- Production `ui://` resources return HTML with inline JS/CSS; there is no static widget asset mount.
- Declare frontend deps in `[gdansk.dependencies]`; run `uv run gdansk lock` after changes.

## Quick-Start Patterns

### Minimal Python server

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server import MCPServer
from mcp.types import TextContent

from gdansk import Ship, Vite

frontend_path = Path(__file__).parent / "views"  # gdansk init scaffolds views/
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

Production widget HTML is self-contained; mount only the MCP app on your public HTTP app.

### Minimal React widget

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

  return <main><h2>Hello</h2></main>;
}
```

### Minimal Vite config

`views/vite.config.ts`

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import gdansk from "@gdansk/vite";

export default defineConfig({
  plugins: [gdansk({ refresh: true }), react()],
});
```

## Integration Selection

| Need | Approach |
| --- | --- |
| New project from scratch | `gdansk init` → [references/cli.md](references/cli.md) |
| Minimal copy-paste layout | [references/quickstart.md](references/quickstart.md) |
| Understand how pieces fit together | [references/architecture.md](references/architecture.md) |
| Add widget to existing server | [rules/path-contract.md](rules/path-contract.md) + [rules/widget-wiring.md](rules/widget-wiring.md) |
| React widget patterns and ext-apps APIs | [references/widgets.md](references/widgets.md) |
| Typed UI data | `structured_output=True` + [references/widgets.md](references/widgets.md) |
| FastAPI embedding | [references/integrations.md](references/integrations.md) |
| Production / CI deploy | [references/production.md](references/production.md) |
| Styling (Tailwind, shadcn/ui) | [references/integrations.md](references/integrations.md) |
| Something broken | [references/troubleshooting.md](references/troubleshooting.md) |

## Agent Workflow

1. **Classify** the request: bootstrap / add widget / extend / debug.
2. **Bootstrap:** `uv add gdansk` → `uv run gdansk init` → `uv run gdansk lock` → `uv run gdansk doctor`.
3. **Wire server:** `Ship` + lifespan + `ship.mcp(...)` — see
   [references/quickstart.md](references/quickstart.md).
4. **Add widget:** Python `@ship.widget` + `widgets/<name>/widget.tsx` — validate
   [rules/path-contract.md](rules/path-contract.md).
5. **Configure Vite:** `@gdansk/vite` with `refresh: true` for development.
6. **Run and verify:** start server; confirm `dist/gdansk-manifest.json` exists and the `ui://` resource renders inline
   JS/CSS.
7. **On failure:** run `uv run gdansk doctor`, then follow
   [references/troubleshooting.md](references/troubleshooting.md).
8. **After fix:** re-verify bundle output and tool calls from the widget UI.

## Task Routing Table

Load only the most relevant reference first. Read additional references only if the task spans multiple areas.

| I want to… | Reference |
| --- | --- |
| Scaffold or use the gdansk CLI | [references/cli.md](references/cli.md) |
| Bootstrap or copy minimal working layout | [references/quickstart.md](references/quickstart.md) |
| Understand architecture and watch modes | [references/architecture.md](references/architecture.md) |
| Check compatibility, deps, verification checklist | [references/adoption.md](references/adoption.md) |
| Build React widgets and call server tools | [references/widgets.md](references/widgets.md) |
| Deploy or run in production / CI | [references/production.md](references/production.md) |
| Metadata, structured output, FastAPI, plain tools, styling | [references/integrations.md](references/integrations.md) |
| Validate `@ship.widget(path=...)` inputs | [references/path-contract.md](references/path-contract.md) |
| Fix errors / missing bundles / render failures | [references/troubleshooting.md](references/troubleshooting.md) |

## Key Practices

- Use the public integration surface: `Ship`, `Vite`, `@ship.widget(...)`, `ship.mcp(...)`, `@gdansk/vite`.
- Prefer `uv run gdansk init` for new projects; `gdansk init` scaffolds `src/<package>/views/`.
- Pass the frontend root to `Vite(...)`, not the `widgets/` directory.
- Register widgets with `path=Path("<dir>/widget.tsx")` relative to `widgets/` inside the frontend root.
- Keep `Vite(Path(...), host=..., port=..., build_directory=...)` aligned with matching `gdansk({...})` options.
- Prefer `uv run gdansk add <alias> <specifier>` for additions; run `uv run gdansk lock` after manual table edits.
- Run frontend tasks via `uv run gdansk dev` or `uv run gdansk build`, not raw `vite` commands.
- Prefer `gdansk({ refresh: true })` when nearby Python or Jinja edits should reload the browser during development.
- Treat production widget HTML as the serving boundary; JS, CSS, and imported assets are inlined into the
  manifest-backed page.

## Common Gotchas

Agents commonly make these mistakes with gdansk:

- Prefixing `@ship.widget(path=...)` with `widgets/` or passing absolute paths.
- Looking for production `client.js` or `client.css` files instead of `dist/gdansk-manifest.json`.
- Mismatching `views/` (CLI scaffold default) with a different frontend dir name without updating `Vite(...)`.
- Running `vite` directly or using npm/deno instead of `uv run gdansk dev` / `uv run gdansk build`.
- Python tool `name` not matching `callServerTool({ name: ... })` in the React widget.
- Widget entry files not named `widget.tsx`/`widget.jsx` or missing a default export.
- Duplicate widget paths raise `The widget ... has already been registered`; duplicate tool names raise
  `A tool with the name ... has already been registered`.
- Host, port, and `buildDirectory` must match on both Python (`Vite(...)`) and Vite (`gdansk({...})`) sides.
- If startup, bundling, or rendering fails after wiring, switch to the troubleshooting reference instead of
  rewriting the integration architecture.

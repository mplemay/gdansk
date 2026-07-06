# Gdansk: React Frontends for Python MCP Servers

> [!WARNING]
> Gdansk is in beta. Its APIs may change before v1.0.

Gdansk connects Python MCP tools to isolated React widget modules. Each widget owns its page metadata and supported
Vite configuration; gdansk builds it into one self-contained HTML resource with inline JavaScript and CSS.

## Installation

```bash
uv add gdansk
uv run gdansk init
uv run gdansk lock
```

Gdansk requires Python `>=3.12,<3.15`, Belgie `>=0.31.0`, and Vite `>=8.1,<9`. Declare frontend dependencies in
`[gdansk.dependencies]` in the Python project's `pyproject.toml`; do not add an app-level `package.json`, `deno.json`,
or `vite.config.ts`.

## Coding-agent skill

The bundled skill is at `src/gdansk/.agents/skills/use-gdansk/`. Use `$use-gdansk` to bootstrap, extend, or debug a
gdansk application.

## Quick start

```text
my-mcp-server/
├── pyproject.toml
├── server.py
└── frontend/
    └── widgets/
        └── hello/
            └── widget.tsx
```

`server.py`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server import MCPServer
from mcp.types import TextContent

from gdansk import Ship, Vite

ship = Ship(vite=Vite(Path(__file__).parent / "frontend"))


@ship.widget(path=Path("hello/widget.tsx"), name="greet")
def greet(name: str = "world") -> list[TextContent]:
    return [TextContent(type="text", text=f"Hello, {name}!")]


@asynccontextmanager
async def lifespan(app: MCPServer) -> AsyncIterator[None]:
    async with ship.mcp(app=app, watch=True):
        yield


mcp = MCPServer(name="Hello server", lifespan=lifespan)
```

`frontend/widgets/hello/widget.tsx`:

```tsx
import { useApp } from "@modelcontextprotocol/ext-apps/react";
import { render } from "@gdansk/widget";

function Hello() {
  const { app, error } = useApp({
    appInfo: { name: "Hello", version: "1.0.0" },
    capabilities: {},
  });

  if (error) return <div>Error: {error.message}</div>;
  if (!app) return <div>Connecting...</div>;

  return (
    <button
      onClick={() => app.callServerTool({ name: "greet", arguments: { name: "MCP" } })}
    >
      Greet
    </button>
  );
}

export default function widget() {
  return render({
    metadata: {
      title: "Hello widget",
      description: "Call the greeting tool",
    },
    widget: <Hello />,
  });
}
```

`pyproject.toml`:

```toml
[gdansk.dependencies]
vite = ">=8.1,<9"
"@gdansk/widget" = "^0.1.0"
"@modelcontextprotocol/ext-apps" = "^1.5.0"
react = "^19"
react-dom = "^19"
```

The widget entry must default-export a function returning `render({...})`. `widget` is a required React element.
HTML metadata belongs in that descriptor. MCP metadata—CSP, visibility, resource URI, icons, and tool
annotations—remains on `@ship.widget(...)`.

Shared page metadata should be exported from a TypeScript module and imported by widgets that use it.

## Per-widget Vite configuration

Import Vite plugins directly in the widget descriptor:

```tsx
import tailwindcss from "@tailwindcss/vite";
import { render } from "@gdansk/widget";

export default function widget() {
  return render({
    metadata: { title: "Tailwind widget" },
    plugins: [tailwindcss()],
    vite: {
      css: { modules: { localsConvention: "camelCaseOnly" } },
      define: { __BUILD_FLAVOR__: JSON.stringify("widget") },
    },
    widget: <main className="p-4">Hello</main>,
  });
}
```

Gdansk strips `plugins` and their imports from the browser bundle during build and dev. Declare plugins inline in
`render({ plugins: [...] })`.

The optional `vite` object supports per-widget resolution, CSS, `define`, and optimization settings. Gdansk owns
`root`, `configFile`, `server`, `build`, `builder`, and `environments`.

Plugin dependencies must be present in `[gdansk.dependencies]`. Bare aliases are recommended; matching `npm:`
specifiers are also accepted. Run `uv run gdansk lock` after dependency changes.

## Watch modes

- `watch=True`: builds each widget on startup, serves complete inline HTML from `gdansk-manifest.json`, and rebuilds on
  file changes.
- `watch=False`: builds each widget on startup and reads `dist/gdansk-manifest.json`.
- `watch=None`: skips frontend tooling and reads a prebuilt manifest.

Use `uv run gdansk dev` for optional standalone Vite HMR when developing widgets outside the MCP host. Production
rejects extra chunks or assets; every manifest widget contains exactly one complete HTML document. No production
static-asset mount is required.

```python
ship = Ship(
    vite=Vite(
        Path(__file__).parent / "frontend",
        host="127.0.0.1",
        port=14000,
        build_directory="public/ui",
    ),
    base_url="https://example.com",
)
```

## CLI

```bash
uv run gdansk init
uv run gdansk add <alias> <specifier>
uv run gdansk lock
uv run gdansk update
uv run gdansk build
uv run gdansk dev
uv run gdansk doctor
uv run gdansk commands
uv run gdansk run <command>
```

The CLI auto-discovers `src/<package>/views` from `[project.scripts]`. Use `--frontend` to override it.

## Examples

- [FastAPI](examples/fastapi)
- [get-time](examples/get-time)
- [production](examples/production)
- [shadcn and Tailwind](examples/shadcn)

## Credits

Gdansk builds on MCP, the Python MCP SDK, React, Vite, Rolldown, and Belgie.

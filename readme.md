# Gdansk: React Frontends for Python MCP Servers

> [!WARNING]
> This project is currently in beta. The APIs are subject to change leading up to v1.0. The v1.0 release will
> coincide with the v2.0 release of the [python mcp sdk](https://github.com/modelcontextprotocol/python-sdk)

## Installation

```bash
uv add gdansk
```

## Skill for Coding Agents

If you use coding agents such as Claude Code or Cursor, add the gdansk skill to your repository:

```shell
npx skills add mplemay/gdansk --skill use-gdansk
```

The skill lives at `src/gdansk/.agents/skills/use-gdansk/` in this repository. Use `$use-gdansk` to bootstrap
integrations, extend widgets and server features, or troubleshoot path, bundling, and render failures. The skill
includes CLI reference (`gdansk init`, `gdansk doctor`), architecture guidance, in-repo examples, and production
deployment patterns.

## Compatibility

- Python: `gdansk` currently requires `>=3.12,<3.15`.
- Frontend dependencies: declare npm and JSR packages in `[gdansk.dependencies]` tables in `pyproject.toml`.
- Runtime tooling: gdansk runs Vite internally through Belgie `Environment`, `Runtime`, and `Command`.

## Examples

- **[FastAPI](examples/fastapi):** Mounting the MCP app inside an existing FastAPI service.
- **[get-time](examples/get-time):** Small copyable widget example for first-time adoption in another repo.
- **[production](examples/production):** Minimal production-rendered and hydrated widget example with a single tool.
- **[shadcn](examples/shadcn):** Multi-tool todo app with `structured_output=True` and `shadcn/ui`.

## Quick Start

Here's a complete example showing how to build a simple greeting tool with a React UI:

**Project Structure:**

```text
my-mcp-server/
├── server.py
├── pyproject.toml
└── frontend/
    ├── vite.config.ts
    └── widgets/
        └── hello/
            └── widget.tsx
```

The `frontend` folder name is only an example. Pass any frontend root to `Vite(...)`.
That frontend root owns its own `vite.config.ts`; dependencies live in the Python project `pyproject.toml`.

**server.py:**

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from mcp.server import MCPServer
from mcp.types import TextContent
from starlette.middleware.cors import CORSMiddleware

from gdansk import Ship, Vite

frontend_path = Path(__file__).parent / "frontend"
ship = Ship(vite=Vite(frontend_path))


@ship.widget(path=Path("hello/widget.tsx"), name="greet")
def greet(name: str) -> list[TextContent]:
    """Greet someone by name."""
    return [TextContent(type="text", text=f"Hello, {name}!")]


@asynccontextmanager
async def lifespan(app: MCPServer) -> AsyncIterator[None]:
    async with ship.mcp(app=app, watch=True):
        yield


mcp = MCPServer(name="Hello World Server", lifespan=lifespan)


def main() -> None:
    app = mcp.streamable_http_app()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    uvicorn.run(app, port=3000)


if __name__ == "__main__":
    main()
```

**frontend/widgets/hello/widget.tsx:**

```tsx
import { useApp } from "@modelcontextprotocol/ext-apps/react";
import { useState } from "react";

export default function App() {
  const [name, setName] = useState("");
  const [greeting, setGreeting] = useState("");

  const { app, error } = useApp({
    appInfo: { name: "Greeter", version: "1.0.0" },
    capabilities: {},
  });

  if (error) return <div>Error: {error.message}</div>;
  if (!app) return <div>Connecting...</div>;

  return (
    <main>
      <h2>Say Hello</h2>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Enter your name..."
      />
      <button
        onClick={async () => {
          const result = await app.callServerTool({
            name: "greet",
            arguments: { name },
          });
          const text = result.content?.find((c) => c.type === "text");
          if (text && "text" in text) setGreeting(text.text);
        }}
      >
        Greet Me
      </button>
      {greeting && <p>{greeting}</p>}
    </main>
  );
}
```

**frontend/vite.config.ts:**

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import gdansk from "@gdansk/vite";

export default defineConfig({
  plugins: [gdansk({ refresh: true }), react()],
});
```

`@gdansk/vite` now provides a default `@` alias that points at the frontend root, so you only need a manual
alias when you want `@` to resolve somewhere else. Use `refresh: true` to trigger full browser reloads when nearby
Python or Jinja files change during development.

`ship.mcp(..., watch=...)` controls how the frontend is prepared:

- **`watch=True`** — runs the Vite dev server in the background with React refresh; JS/CSS load from the Vite origin.
- **`watch=False`** (default) — runs `vite build` on startup, then loads the inline gdansk manifest from the build
  directory.
- **`watch=None`** — skips the frontend build toolchain entirely and loads an existing `gdansk-manifest.json` under the
  build directory. Use this when widgets are prebuilt (for example in CI) to avoid cold-start build cost.

If you need a non-default build output directory, keep the Vite plugin and Python runtime aligned. Widget sources
always live under `widgets/` at the frontend root (`Vite(root=...)` / Vite `root`).

```python
ship = Ship(
    vite=Vite(
        Path(__file__).parent / "frontend",
        build_directory="public/ui",
    ),
)
```

```ts
export default defineConfig({
  plugins: [
    gdansk({
      buildDirectory: "public/ui",
      refresh: true,
    }),
    react(),
  ],
});
```

Production widgets are rendered as a single HTML resource. The generated page includes inline `<style>` tags and a
single inline `<script type="module">`, so no static widget asset mount is required.

The default production output is intentionally small:

- gdansk runtime manifest: `dist/gdansk-manifest.json`
- one inline script payload per widget
- inline CSS payloads per widget
- imported assets from the Vite graph inlined as data URLs

If your MCP client renders widget HTML on a different origin, pass `base_url` to `Ship` so widget metadata can describe
the public server origin:

```python
ship = Ship(vite=Vite(Path(__file__).parent / "frontend"), base_url="https://example.com")
```

If you want a different dev runtime host or port, configure both sides explicitly:

```python
from gdansk import Ship, Vite

ship = Ship(vite=Vite(Path(__file__).parent / "frontend", host="127.0.0.1", port=14000))
```

```ts
export default defineConfig({
  plugins: [gdansk({ host: "127.0.0.1", port: 14000, refresh: true }), react()],
});
```

Lock frontend dependencies from the Python project root after editing them:

```bash
uv run gdansk lock
```

## CLI

Gdansk ships a CLI for project setup and frontend tooling:

```bash
uv run gdansk init
uv run gdansk add <alias> <specifier>
uv run gdansk lock
uv run gdansk update
uv run gdansk build
uv run gdansk dev
uv run gdansk run <command>
uv run gdansk commands
uv run gdansk doctor
```

The CLI auto-discovers the frontend root at `src/<package>/views`, using `[project.scripts]` entry points to
identify the Python package. Override that path per command with `--frontend` when needed.

## Frontend Dependencies

Use `[gdansk.dependencies]`, grouped dependency tables such as `[gdansk.dependencies.dev]`, and `[gdansk.commands]` in
`pyproject.toml` when frontend builds need npm or JSR packages:

```toml
[gdansk.dependencies]
react = "^19"
vite = "8.0.8"
"@gdansk/vite" = "^0.1.0"
std_path = "jsr:@std/path@^1"

[gdansk.dependencies.dev]
"@types/react" = "^19"

[gdansk.commands]
lint = ["oxlint", "--fix"]
```

Unprefixed values are treated as npm version requirements for the table key, so `react = "^19"` becomes `npm:react@^19`.
Use `uv run gdansk add <alias> <specifier>`, `uv run gdansk lock`, or `uv run gdansk update` to resolve dependencies and
write `deno.lock` next to `pyproject.toml`. `gdansk build` and `gdansk dev` invoke Vite internally; entries under
`[gdansk.commands]` are optional user commands executed by `gdansk run`.

Gdansk mounts your default export into `#root` automatically and wraps it with `React.StrictMode`.

Run the server with `uv run python server.py`, configure it in your MCP client (like Claude Desktop), and you'll have
an interactive greeting tool ready to use.

## Why Use Gdansk?

1. **Python Backend, React Frontend** — Use familiar technologies you already know. Write your logic in Python with type
   hints, build your UI in React/TypeScript. No need to learn a new framework-specific language.

2. **Built for MCP** — Composes with `MCPServer` from the official Python SDK: register widget tools and HTML resources
   via `Ship`, wire them in with `ship.mcp(app=...)`, and integrate with Claude Desktop and other MCP clients.

3. **Fast bundling with Rolldown** — The Rolldown bundler processes your TypeScript/JSX automatically. Hot-reload in
   development mode means you see changes instantly without manual rebuilds.

4. **Type-Safe** — Full type safety across the stack. Python type hints on the backend, TypeScript on the frontend, with
   automatic type checking via ruff and TypeScript compiler.

5. **Developer-Friendly** — Simple decorator API (`@ship.widget()`), automatic resource registration, dev mode on
   `ship.mcp(...)`, and comprehensive error messages. Get started in minutes, not hours.

6. **Production Ready** — Comprehensive test suite covering Python 3.12+ across Linux, macOS, and Windows. Used in
   production MCP servers with proven reliability.

## Credits

Gdansk builds on the shoulders of giants:

- **[Model Context Protocol](https://modelcontextprotocol.io/)** — Official MCP documentation
- **[@modelcontextprotocol/ext-apps](https://www.npmjs.com/package/@modelcontextprotocol/ext-apps)** — React hooks for
  MCP apps
- **[Rolldown](https://rolldown.rs/)** — Fast JavaScript bundler
- **[mcp/python-sdk](https://github.com/modelcontextprotocol/python-sdk)** — Python SDK for MCP server development

Special thanks to the Model Context Protocol team at Anthropic for creating the MCP standard and the
`@modelcontextprotocol/ext-apps` package.

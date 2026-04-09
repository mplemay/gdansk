# Gdansk: React Frontends for Python MCP Servers

> [!WARNING]
> This project is currently in beta. The APIs are subject to change leading up to v1.0. The v1.0 release will
> coincide with the v2.0 release of the [python mcp sdk](https://github.com/modelcontextprotocol/python-sdk)

## Installation

```bash
uv add gdansk
```

## Skill for Coding Agents

If you use coding agents such as Claude Code or Cursor, we recommend adding this skill to your repository:

```shell
npx skills add mplemay/gdansk
```

## Examples

- **[FastAPI](examples/fastapi):** FastAPI-based MCP server integration with mounted app routes.
- **[get-time](examples/get-time):** Feature-rich MCP app covering tool calls, messaging, logging, and links.
- **[ssr](examples/ssr):** Minimal example with a single tool UI.
- **[shadcn](examples/shadcn):** Todo app example using `shadcn/ui` components with Gdansk.

## Quick Start

Here's a complete example showing how to build a simple greeting tool with a React UI:

**Project Structure:**

```text
my-mcp-server/
├── server.py
└── views/
    ├── package.json
    └── widgets/
        └── hello/
            └── widget.tsx
```

The `views` folder name is only an example: pass any directory to `Ship(..., views=...)` (for example
`Path(__file__).parent / "frontend"`).
That frontend package owns its own `vite.config.ts`; import `@gdansk/vite` there alongside any framework plugins.

**server.py:**

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


@ship.widget(path=Path("hello/widget.tsx"), name="greet")
def greet(name: str) -> list[TextContent]:
    """Greet someone by name."""
    return [TextContent(type="text", text=f"Hello, {name}!")]


@asynccontextmanager
async def lifespan(app: MCPServer) -> AsyncIterator[None]:
    async with ship.mcp(app=app, dev=True):
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

**views/widgets/hello/widget.tsx:**

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
            arguments: { name }
          });
          const text = result.content?.find(c => c.type === "text");
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

**views/vite.config.ts:**

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import gdansk from "@gdansk/vite";

export default defineConfig({
  plugins: [gdansk(), react()],
});
```

If you want a different SSR host or port, configure both sides explicitly:

```python
ship = Ship(views=Path(__file__).parent / "views", host="127.0.0.1", port=14000)
```

```ts
export default defineConfig({
  plugins: [gdansk({ host: "127.0.0.1", port: 14000 }), react()],
});
```

Install the frontend package dependencies from `views/` after editing them:

```bash
cd views
uv run deno install
```

Gdansk mounts your default export into `#root` automatically and wraps it with `React.StrictMode`.

Run the server with `python server.py`, configure it in your MCP client (like Claude Desktop), and you'll have an
interactive greeting tool ready to use.

## Why Use Gdansk?

1. **Python Backend, React Frontend** — Use familiar technologies you already know. Write your logic in Python with type
   hints, build your UI in React/TypeScript. No need to learn a new framework-specific language.

2. **Built for MCP** — Composes with `MCPServer` from the official Python SDK: register widget tools and HTML resources
   via `Ship`, wire them in with `ship.mcp(app=...)`, and integrate with Claude Desktop and other MCP clients.

3. **Rust-Powered Bundling** — Lightning-fast Rolldown bundler processes your TypeScript/JSX automatically. Hot-reload
   in development mode means you see changes instantly without manual rebuilds.

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
- **[Rolldown](https://rolldown.rs/)** — Fast Rust-based JavaScript bundler
- **[PyO3](https://github.com/PyO3/pyo3)** — Rust bindings for Python
- **[mcp/python-sdk](https://github.com/modelcontextprotocol/python-sdk)** — Python SDK for MCP server development
- **[Deno Core](https://docs.rs/deno_core/latest/deno_core/)** — JavaScript runtime that powers Gdansk's Rust runtime

Special thanks to the Model Context Protocol team at Anthropic for creating the MCP standard and the
`@modelcontextprotocol/ext-apps` package.

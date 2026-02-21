# Gdansk: React Frontends for Python MCP Servers

> [!WARNING]
> This project is currently in open-beta. The APIs are subject to change leading up to v1.0. The v1.0 release will
> coincide with the v2.0 release of the [python mcp sdk](https://github.com/modelcontextprotocol/python-sdk)

The name "Gdansk" (pronounced "guh-DANSK") is a nod to the city's historical role as a bridge between cultures and trade
routes—much like this framework bridges Python backends and React frontends.

Gdansk bridges Python backend logic with React/TypeScript UIs, letting you create rich, interactive tools for Model
Context Protocol (MCP) servers without leaving the Python ecosystem.

Gdansk combines [FastMCP](https://github.com/jlowin/fastmcp) for server-side Python logic with React for client-side
interfaces, and uses [Rolldown](https://rolldown.rs/) (a Rust-based bundler) to handle all the JavaScript/TypeScript
bundling automatically. Whether you're building data visualization tools, form-based interfaces, or interactive
dashboards for Claude Desktop and other MCP clients, Gdansk provides a straightforward path from Python functions to
polished UIs.


## Installation

```bash
uv add gdansk
```

## Examples

- **[FastAPI](examples/fastapi):** FastAPI-based MCP server integration with mounted app routes.
- **[get-time](examples/get-time):** Feature-rich MCP app covering tool calls, messaging, logging, and links.
- **[ssr](examples/ssr):** Minimal SSR example using `Amber(ssr=True)` with a single tool UI.
- **[shadcn](examples/shadcn):** Todo app example using `shadcn/ui` components with Gdansk.

## Quick Start

Here's a complete example showing how to build a simple greeting tool with a React UI:

**Project Structure:**

```text
my-mcp-server/
├── server.py
└── views/
    ├── package.json
    └── apps/
        └── hello/
            └── app.tsx
```

**server.py:**

```python
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
from gdansk import Amber
import uvicorn

mcp = FastMCP("Hello World Server")
amber = Amber(mcp=mcp, views=Path(__file__).parent / "views")

@amber.tool(name="greet", ui=Path("hello/app.tsx"))
def greet(name: str) -> list[TextContent]:
    """Greet someone by name."""
    return [TextContent(type="text", text=f"Hello, {name}!")]

if __name__ == "__main__":
    app = amber(dev=True)  # Enable hot-reload for development
    uvicorn.run(app, port=3000)
```

**views/apps/hello/app.tsx:**

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

Gdansk mounts your default export into `#root` automatically and wraps it with `React.StrictMode`.

Run the server with `python server.py`, configure it in your MCP client (like Claude Desktop), and you'll have an
interactive greeting tool ready to use.

## Why Use Gdansk?

1. **Python Backend, React Frontend** — Use familiar technologies you already know. Write your logic in Python with type
   hints, build your UI in React/TypeScript. No need to learn a new framework-specific language.

2. **Built for MCP** — First-class support for FastMCP servers. Automatic resource registration, MCP app protocol
   handling, and seamless integration with Claude Desktop and other MCP clients.

3. **Rust-Powered Bundling** — Lightning-fast Rolldown bundler processes your TypeScript/JSX automatically. Hot-reload
   in development mode means you see changes instantly without manual rebuilds.

4. **Type-Safe** — Full type safety across the stack. Python type hints on the backend, TypeScript on the frontend, with
   automatic type checking via ruff and TypeScript compiler.

5. **Developer-Friendly** — Simple decorator API (`@amber.tool()`), automatic resource registration, hot-reload dev
   mode, and comprehensive error messages. Get started in minutes, not hours.

6. **Production Ready** — Comprehensive test suite covering Python 3.11-3.14 across Linux, macOS, and Windows. Used in
   production MCP servers with proven reliability.


## Resources

- **[Model Context Protocol](https://modelcontextprotocol.io/)** — Official MCP documentation
- **[mcp/python-sdk](https://github.com/modelcontextprotocol/python-sdk)** — Python SDK for building MCP servers
- **[@modelcontextprotocol/ext-apps](https://www.npmjs.com/package/@modelcontextprotocol/ext-apps)** — React hooks for
  MCP apps
- **[Rolldown](https://rolldown.rs/)** — Rust-powered JavaScript bundler
- **[Deno Core](https://docs.rs/deno_core/latest/deno_core/)** — JavaScript runtime foundation used in Gdansk's Rust
  runtime layer

## Credits

Gdansk builds on the shoulders of giants:

- **[Rolldown](https://rolldown.rs/)** — Fast Rust-based JavaScript bundler
- **[PyO3](https://github.com/PyO3/pyo3)** — Rust bindings for Python
- **[mcp/python-sdk](https://github.com/modelcontextprotocol/python-sdk)** — Python SDK for MCP server development
- **[Deno Core](https://docs.rs/deno_core/latest/deno_core/)** — JavaScript runtime that powers Gdansk's Rust runtime

Special thanks to the Model Context Protocol team at Anthropic for creating the MCP standard and the
`@modelcontextprotocol/ext-apps` package.

---

Made with ❤️ by [Matt LeMay](https://github.com/mattlemay)

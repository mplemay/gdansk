# Gdansk

[![Test](https://github.com/mattlemay/gdansk/actions/workflows/test.yml/badge.svg)](https://github.com/mattlemay/gdansk/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Build interactive React frontends for your MCP tools using Python.** Gdansk bridges Python backend logic with
React/TypeScript UIs, letting you create rich, interactive tools for Model Context Protocol (MCP) servers without
leaving the Python ecosystem.

Gdansk combines [FastMCP](https://github.com/jlowin/fastmcp) for server-side Python logic with React for client-side
interfaces, and uses [Rolldown](https://rolldown.rs/) (a Rust-based bundler) to handle all the JavaScript/TypeScript
bundling automatically. Whether you're building data visualization tools, form-based interfaces, or interactive
dashboards for Claude Desktop and other MCP clients, Gdansk provides a straightforward path from Python functions to
polished UIs.

Contributing: see [CONTRIBUTING.md](CONTRIBUTING.md).

The name "Gdansk" (pronounced "guh-DANSK") is a nod to the city's historical role as a bridge between cultures and trade
routes—much like this framework bridges Python backends and React frontends.

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

## Installation

```bash
uv add gdansk
```

**Requirements:**

- Python 3.11 or later
- Node.js (for frontend dependencies)

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

## Feature-Rich Example

For a more comprehensive example showcasing all available features, see the [get-time example](examples/get-time) in
this repository. It demonstrates:

- **Calling tools** with `app.callServerTool()` — Invoke Python functions from React
- **Sending messages** with `app.sendMessage()` — Send user messages to the MCP client
- **Logging** with `app.sendLog()` — Send log messages for debugging
- **Opening links** with `app.openLink()` — Open URLs in the user's browser
- **CSS imports** — Style your components with imported stylesheets
- **Multiple UI interactions** — Build rich, multi-action interfaces

The get-time example provides a working template you can clone and adapt for your own MCP tools.
For a minimal server-side rendering setup, see the [ssr example](examples/ssr).

## Key Concepts

### The Amber Class

Initialize Amber with your FastMCP server and views directory:

```python
from gdansk import Amber
from pathlib import Path

amber = Amber(
    mcp=mcp,                           # Your FastMCP server instance
    views=Path("./views"),             # Directory containing package.json and apps/
    metadata={"title": "My MCP App"},  # Optional: static HTML metadata for all tools
)
```

Bundled assets are always written to `views/.gdansk` and this output path is not configurable on `Amber`.

Create your app with Amber to bundle and serve your UIs:

```python
app = amber(dev=True)    # dev=True enables hot-reload and uses non-minified output
uvicorn.run(app, port=3000)
```

`Amber.__call__` supports `dev` only. `dev=True` runs bundling/watch in the background and disables minification;
`dev=False` blocks for an initial minified build.

### Tool Registration

The `@amber.tool()` decorator registers both a tool and its UI resource:

```python
@amber.tool(
    name="my-tool",           # Tool name (optional, defaults to function name)
    ui=Path("my-tool/app.tsx"),  # Path to UI file relative to views/apps directory
    title="My Tool",          # Optional: display title
    description="...",        # Optional: tool description
    annotations=...,          # Optional: MCP tool annotations
    icons=[...],              # Optional: tool icons
    meta={...},               # Optional: MCP tool metadata (ui resource metadata is added automatically)
    metadata={...},           # Optional: HTML metadata for this tool only
    structured_output=False,  # Optional: structured output support
)
def my_tool(arg: str) -> list[TextContent]:
    """Tool implementation."""
    return [TextContent(type="text", text=f"Result: {arg}")]
```

The UI file must match `**/app.tsx` or `**/app.jsx`, relative to your `views/apps` directory.

### React Integration

Use the `useApp()` hook from `@modelcontextprotocol/ext-apps/react` to interact with the MCP protocol:

```tsx
import { useApp } from "@modelcontextprotocol/ext-apps/react";

function MyApp() {
  const { app, error } = useApp({
    appInfo: { name: "My App", version: "1.0.0" },
    capabilities: {},
  });

  if (error) return <div>Error: {error.message}</div>;
  if (!app) return <div>Connecting...</div>;

  // Call Python tools
  const result = await app.callServerTool({
    name: "my-tool",
    arguments: { arg: "value" }
  });

  // Send messages to the MCP client
  app.sendMessage({
    role: "user",
    content: [{ type: "text", text: "Hello!" }]
  });

  // Send logs (for debugging)
  app.sendLog({ level: "info", data: "Debug message" });

  // Open links in the user's browser
  app.openLink({ url: "https://example.com" });

  return <div>Your UI here</div>;
}
```

## Development Workflow

**Setting up a new project:**

```bash
# Create project directory
mkdir my-mcp-server && cd my-mcp-server

# Initialize Python environment
uv init
uv add gdansk mcp uvicorn

# Create views directory
mkdir -p views/apps/hello

# Install frontend dependencies inside views/
cd views
npm install @modelcontextprotocol/ext-apps react react-dom
npm install -D @types/react @types/react-dom typescript
cd ..
```

**Development mode:**

Start your server with `dev=True` to enable hot-reload:

```python
app = amber(dev=True)
uvicorn.run(app, port=3000)
```

Make changes to your TSX/JSX files, and the bundler will automatically rebuild. Refresh the UI in your MCP client to see
updates.

**Production builds:**

For production, use `dev=False` (or omit the parameter) to create optimized builds:

```python
app = amber(dev=False)
uvicorn.run(app, port=3000)
```

**Testing in Claude Desktop:**

Configure your MCP server in Claude Desktop's config file (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "my-server": {
      "command": "uv",
      "args": ["run", "python", "/path/to/server.py"]
    }
  }
}
```

Restart Claude Desktop to load your server.

## Examples & Resources

### Examples

- **[FastAPI](examples/fastapi):** FastAPI-based MCP server integration with mounted app routes.
- **[get-time](examples/get-time):** Feature-rich MCP app covering tool calls, messaging, logging, and links.
- **[ssr](examples/ssr):** Minimal SSR example using `Amber(ssr=True)` with a single tool UI.
- **[shadcn](examples/shadcn):** Todo app example using `shadcn/ui` components with Gdansk.

### Resources

- **[Model Context Protocol](https://modelcontextprotocol.io/)** — Official MCP documentation
- **[mcp/python-sdk](https://github.com/modelcontextprotocol/python-sdk)** — Python SDK for building MCP servers
- **[@modelcontextprotocol/ext-apps](https://www.npmjs.com/package/@modelcontextprotocol/ext-apps)** — React hooks for
  MCP apps
- **[Rolldown](https://rolldown.rs/)** — Rust-powered JavaScript bundler
- **[Deno Core](https://docs.rs/deno_core/latest/deno_core/)** — JavaScript runtime foundation used in Gdansk's Rust
  runtime layer

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

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

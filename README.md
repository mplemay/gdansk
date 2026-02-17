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
# Using uv (recommended)
uv add gdansk

# Or using pip
pip install gdansk
```

**Requirements:**

- Python 3.11 or later
- Node.js (for frontend dependencies, installed automatically)

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
    app = mcp.streamable_http_app()
    with amber(dev=True):  # Enable hot-reload for development
        uvicorn.run(app, port=3000)
```

**views/apps/hello/app.tsx:**

```tsx
import { useApp } from "@modelcontextprotocol/ext-apps/react";
import { useState } from "react";
import { createRoot } from "react-dom/client";

function GreetingApp() {
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

createRoot(document.getElementById("root")!).render(<GreetingApp />);
```

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

## How It Works

1. **Define tools** — Use the `@amber.tool()` decorator on your Python functions, specifying the UI file with the `ui`
   parameter.

2. **Bundling** — Gdansk automatically bundles your TypeScript/JSX files using Rolldown (a fast Rust-based bundler) into
   browser-ready JavaScript.

3. **Resource registration** — Bundled UIs are served as MCP resources with the `text/html;profile=mcp-app` MIME type,
   which MCP clients recognize as interactive apps.

4. **Rendering** — MCP clients (like Claude Desktop) render the UI in their interface when the tool is invoked.

5. **Communication** — Your React UI calls back to Python tools via the MCP protocol using the `useApp()` hook and
   methods like `app.callServerTool()`.

**Development mode:** Use `amber(dev=True)` as a context manager to enable hot-reload. Changes to your TSX/JSX files are
automatically rebundled, and you can refresh the UI in your MCP client to see updates instantly.

## Key Concepts

### The Amber Class

Initialize Amber with your FastMCP server and views directory:

```python
from gdansk import Amber
from pathlib import Path

amber = Amber(
    mcp=mcp,                           # Your FastMCP server instance
    views=Path("./views"),             # Directory containing package.json and apps/
    output=Path(".gdansk"),            # Optional: bundled output directory (default: .gdansk)
    metadata={"title": "My MCP App"},  # Optional: static HTML metadata for all tools
)
```

Use the context manager to bundle and serve your UIs:

```python
with amber(dev=True):    # dev=True enables hot-reload
    uvicorn.run(app, port=3000)
```

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
with amber(dev=True):
    uvicorn.run(app, port=3000)
```

Make changes to your TSX/JSX files, and the bundler will automatically rebuild. Refresh the UI in your MCP client to see
updates.

**Production builds:**

For production, use `dev=False` (or omit the parameter) to create optimized builds:

```python
with amber(dev=False):
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

- **[get-time example](examples/get-time)** — Complete working example showcasing all Gdansk features
- **[Model Context Protocol](https://modelcontextprotocol.io/)** — Official MCP documentation
- **[FastMCP](https://github.com/jlowin/fastmcp)** — Python framework for building MCP servers
- **[@modelcontextprotocol/ext-apps](https://www.npmjs.com/package/@modelcontextprotocol/ext-apps)** — React hooks for
  MCP apps
- **[Rolldown](https://rolldown.rs/)** — Rust-powered JavaScript bundler

## Contributing

Contributions are welcome! To set up a development environment:

```bash
# Clone the repository
git clone https://github.com/mattlemay/gdansk.git
cd gdansk

# Install dependencies
uv sync --all-extras

# Run tests
uv run pytest

# Run linters
uv run ruff check .
uv run ruff format .

# Run type checker
uv run ty check src
```

For more details, see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

## Credits

Gdansk builds on the shoulders of giants:

- **[Rolldown](https://rolldown.rs/)** — Fast Rust-based JavaScript bundler
- **[PyO3](https://github.com/PyO3/pyo3)** — Rust bindings for Python
- **[FastMCP](https://github.com/jlowin/fastmcp)** — Python MCP server framework
- **[maturin](https://github.com/PyO3/maturin)** — Build tool for Rust/Python hybrid projects

Special thanks to the Model Context Protocol team at Anthropic for creating the MCP standard and the
`@modelcontextprotocol/ext-apps` package.

---

Made with ❤️ by [Matt LeMay](https://github.com/mattlemay)

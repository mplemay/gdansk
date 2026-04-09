# SSR example

## Run

```bash
uv sync
uv run main
```

The Python server uses `MCPServer` with a lifespan that enters `ship.mcp(app=...)` so widget tools and HTML resources
are registered on the MCP app.

The tool UI is rendered on the server with `renderToString`, then hydrated client-side.

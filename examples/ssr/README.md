# SSR example

This example shows the minimal production rendering flow: one widget tool, server-rendered HTML, and client-side
hydration.

## Run

```bash
uv sync
uv run main
```

The Python server uses `MCPServer` with a lifespan that enters `ship.mcp(app=...)` so widget tools and HTML resources
are registered on the MCP app.

The tool UI is rendered on the server with `renderToString`, then hydrated client-side. Development still uses
`ship.mcp(..., dev=True)` so the Vite dev server runs in the background with refresh enabled.

For agent-driven setup, prefer `$use-gdansk`. For SSR failures or missing bundle output, prefer `$debug-gdansk`.

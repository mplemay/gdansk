# SSR example

This example shows the minimal server-side rendering flow: one widget tool, server-side HTML rendering, and client-side
hydration.

## Run

```bash
uv sync
uv run main
```

The Python server uses `MCPServer` with a lifespan that enters `ship.mcp(app=...)` so widget tools and HTML resources
are registered on the MCP app.

The example opts into production SSR on both sides with `Ship(ssr=True)` and `gdansk({ ssr: true })`.
The tool UI is rendered on the server with `renderToString`, then hydrated client-side.

For agent-driven setup, prefer `$use-gdansk`. For SSR failures or missing bundle output, prefer `$debug-gdansk`.

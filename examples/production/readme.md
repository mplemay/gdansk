# Production example

This example shows the minimal production flow: one widget tool and self-contained widget HTML with inline JS/CSS.

## Run

```bash
uv sync
uv run main
```

The Python server uses `MCPServer` with a lifespan that enters `ship.mcp(app=...)` so widget tools and HTML resources
are registered on the MCP app.

Production builds only `dist/gdansk-manifest.json`; there is no static widget asset mount or separate JS runtime
server. Development still uses `ship.mcp(..., watch=True)` so the Vite dev server runs in the background with refresh
enabled.

For agent-driven setup or troubleshooting, prefer `$use-gdansk`.

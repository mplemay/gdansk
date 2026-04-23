# Production example

This example shows the minimal production flow: one widget tool, hydration-only HTML from Python,
and client-side hydration from statically served assets.

## Run

```bash
uv sync
uv run main
```

The Python server uses `MCPServer` with a lifespan that enters `ship.lifespan(app=...)` so widget tools and HTML
resources are registered on the MCP app.

Production builds only static assets plus `gdansk-manifest.json`; there is no separate JS runtime server. Development
still uses `ship.lifespan(..., watch=True)` so the Vite dev server runs in the background with refresh enabled.

For agent-driven setup, prefer `$use-gdansk`. For render/runtime failures or missing bundle output, prefer
`$debug-gdansk`.

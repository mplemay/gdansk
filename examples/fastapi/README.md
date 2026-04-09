# FastAPI example

This example shows how to mount the gdansk-backed MCP app inside an existing FastAPI service. Use it when the user
already has an ASGI app and needs `mcp.streamable_http_app(streamable_http_path="/")` mounted at a subpath while
keeping the nested lifespan wiring correct.

## Run

```bash
uv sync
uv run fastapi dev main.py
```

## Production mode

```bash
PRODUCTION=true uv run fastapi run main.py
```

The MCP app is mounted at `/mcp` and uses `streamable_http_path="/"` inside the mounted app.

For agent-driven setup, prefer `$use-gdansk`. For broken mounted integrations, prefer `$debug-gdansk`.

# FastAPI example

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

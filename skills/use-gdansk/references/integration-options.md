# Integration Options

Use this file when the request goes beyond basic widget wiring.

## Metadata behavior

`Ship` accepts optional `metadata` using the `Metadata` shape from `gdansk.metadata` (a `TypedDict`).

```python
from gdansk import Ship
from gdansk.metadata import Metadata

meta: Metadata = {
    "title": "Root App",
    "description": "Shared description",
    "openGraph": {"title": "Shared OG"},
}

ship = Ship(views=views_path, metadata=meta)
```

Per-widget metadata can be passed directly to `@ship.widget(..., metadata=...)`.

Merge semantics for metadata helpers (such as `merge_metadata` in `gdansk.metadata`) are shallow top-level merge when
you combine sources in application code.

## Widget resource metadata

`Ship` also accepts optional `resource_meta` for widget resource `_meta`, separate from HTML head `metadata` and tool
`meta`.

```python
from gdansk import ResourceMeta, Ship

resource_meta: ResourceMeta = {
    "openai/widgetDescription": "Shows an interactive widget.",
    "ui": {
        "csp": {
            "connectDomains": ["https://api.example.com"],
            "resourceDomains": ["https://cdn.example.com"],
        }
    },
}

ship = Ship(
    views=views_path,
    base_url="https://example.com/app",
    resource_meta=resource_meta,
)
```

When `base_url` is set, gdansk automatically derives a same-origin widget domain and CSP baseline for the `ui://...`
resource:

- `ui.domain` becomes the normalized origin of `base_url`
- `ui.csp.connectDomains` includes that origin
- `ui.csp.resourceDomains` includes that origin

Per-widget `@ship.widget(..., resource_meta=...)` overrides the domain and appends additional CSP domains with
ordered de-duplication.

## Widget decorator surface

`Ship.widget(...)` supports the following public knobs that matter for repo integrations:

- `name`
- `title`
- `description`
- `annotations`
- `icons`
- `meta`
- `metadata`
- `resource_meta`
- `structured_output`

Prefer these public arguments over custom wrapper logic when the request only needs tool metadata or typed output.

## Structured output

Use `structured_output=True` when the UI should receive typed data rather than parse text content manually.

```python
@ship.widget(path=Path("todo/widget.tsx"), name="list-todos", structured_output=True)
def list_todos() -> list[Todo]:
    return todos
```

## Custom runtime host or port

The default frontend runtime address is `127.0.0.1:13714`. If you change it, keep Python and Vite in sync:

```python
ship = Ship(views=views_path, host="127.0.0.1", port=14000)
```

```ts
export default defineConfig({
  plugins: [gdansk({ host: "127.0.0.1", port: 14000 }), react()],
});
```

## Plain MCP tools (no React UI)

Register tools on the same `MCPServer` instance that you pass into `ship.mcp(app=...)`:

```python
mcp = MCPServer(name="My Server", lifespan=lifespan)


@mcp.tool(name="ping")
def ping() -> str:
    return "pong"
```

Use `mcp.add_tool(...)` if you prefer imperative registration.

## FastAPI mounting pattern

When embedding the MCP Streamable HTTP app in FastAPI, use `streamable_http_path="/"` on the inner app and wire both
lifespans:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from mcp.server import MCPServer

from gdansk import Ship

frontend_path = Path(__file__).parent / "frontend"
ship = Ship(views=frontend_path)


@asynccontextmanager
async def mcp_lifespan(app: MCPServer) -> AsyncIterator[None]:
    async with ship.mcp(app=app, dev=True):
        yield


mcp = MCPServer(name="FastAPI Example Server", lifespan=mcp_lifespan)
mcp_app = mcp.streamable_http_app(streamable_http_path="/")


@asynccontextmanager
async def lifespan(_: object) -> AsyncIterator[None]:
    async with mcp_app.router.lifespan_context(mcp_app):
        yield


app = FastAPI(lifespan=lifespan)
app.mount(path="/assets", app=ship.assets)
app.mount(path="/mcp", app=mcp_app)
```

`gdansk` production widgets expect hydration assets at `/<assets_dir>/...`. With the default `assets="assets"`, mount
`ship.assets` at `/assets`.

## Styling and Tailwind

Style widgets with normal frontend tooling in the frontend package (for example PostCSS, Tailwind, or component
libraries). Put Vite-specific setup in `vite.config.ts`, import `@gdansk/vite` there, and keep framework plugins in
that same file. Declare dependencies in `package.json`, run `uv run deno install` from the frontend package directory,
and commit `deno.lock` when it changes.

## Decision matrix

| Need | Option |
| --- | --- |
| Shared head metadata across widgets | constructor `metadata=` (`gdansk.metadata.Metadata`) |
| Per-widget title or OG override | `@ship.widget(..., metadata=...)` |
| Typed tool responses for the UI | `@ship.widget(..., structured_output=True)` |
| Running inside existing FastAPI service | mount `mcp_app` + nested lifespan |
| Tool without a React surface | `@mcp.tool` / `add_tool` on `MCPServer` |

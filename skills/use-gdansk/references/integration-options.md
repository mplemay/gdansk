# Integration Options

Use this file when the request goes beyond basic widget wiring.

## SSR options

### Global SSR default

Enable SSR for all registered widgets by default:

```python
ship = Ship(views=views_path, ssr=True)
```

### Per-widget SSR override

Override the global setting on specific widgets:

```python
@ship.widget(path=Path("reports/widget.tsx"), ssr=True)
def reports():
    ...

@ship.widget(path=Path("settings/widget.tsx"), ssr=False)
def settings():
    ...
```

Behavior:

- Widget-level `ssr` overrides constructor `ssr`.
- If effective SSR is `True`, server bundle is required.
- If effective SSR is `False`, no server runtime execution occurs.

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

Per-widget metadata can be passed to `@ship.widget` where supported in `core.py` (see that module for current kwargs).

Merge semantics for metadata helpers (such as `merge_metadata` in `gdansk.metadata`) are shallow top-level merge when
you combine sources in application code.

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

ship = Ship(views=Path(__file__).parent / "views")


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
app.mount(path="/mcp", app=mcp_app)
```

## Styling and Tailwind

Style widgets with normal frontend tooling in the `views` package (for example PostCSS, Tailwind, or component
libraries). Declare dependencies in `views/package.json`, run `uv run deno install` from `views/`, and commit
`deno.lock` when it changes; gdansk does not ship a separate Vite plugin API in the public Python package.

## Decision matrix

| Need | Option |
| --- | --- |
| Server-rendered initial HTML for all widgets | `Ship(..., ssr=True)` |
| Server-rendered initial HTML for one widget | `@ship.widget(..., ssr=True)` |
| Force client-only rendering for one widget while global SSR is on | `@ship.widget(..., ssr=False)` |
| Shared head metadata across widgets | constructor `metadata=` (`gdansk.metadata.Metadata`) |
| Per-widget title or OG override | `@ship.widget(..., metadata=...)` when supported |
| Running inside existing FastAPI service | mount `mcp_app` + nested lifespan |
| Tool without a React surface | `@mcp.tool` / `add_tool` on `MCPServer` |

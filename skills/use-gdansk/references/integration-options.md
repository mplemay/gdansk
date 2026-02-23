# Integration Options

Use this file when the request goes beyond basic tool-page wiring.

## SSR options

### Global SSR default

Enable SSR for all registered pages by default:

```python
amber = Amber(mcp=mcp, views=views_path, ssr=True)
```

### Per-tool SSR override

Override the global setting on specific tools:

```python
@amber.tool(page=Path("reports"), ssr=True)
def reports():
    ...

@amber.tool(page=Path("settings"), ssr=False)
def settings():
    ...
```

Behavior:

- Tool-level `ssr` overrides constructor `ssr`.
- If effective SSR is `True`, server bundle is required.
- If effective SSR is `False`, no server runtime execution occurs.

## `cache_html` behavior

Default:

```python
amber = Amber(mcp=mcp, views=views_path, cache_html=True)
```

With caching enabled, rendered HTML is reused until the bundle fingerprint changes:

- client JS mtime/size
- server JS mtime/size (if present)
- CSS mtime/size (or presence change)

Disable caching when HTML must be freshly rendered each request:

```python
amber = Amber(mcp=mcp, views=views_path, cache_html=False)
```

## Metadata behavior

Set global metadata on `Amber`:

```python
amber = Amber(
    mcp=mcp,
    views=views_path,
    metadata={
        "title": "Root App",
        "description": "Shared description",
        "openGraph": {"title": "Shared OG"},
    },
)
```

Override per tool:

```python
@amber.tool(
    page=Path("hello"),
    metadata={"title": "Tool Title", "openGraph": {"title": "Tool OG"}},
)
def hello():
    ...
```

Merge semantics are shallow top-level merge:

- tool metadata replaces same top-level keys from constructor metadata
- nested objects are replaced, not deep merged

## FastAPI mounting pattern

When embedding MCP app in FastAPI, use `streamable_http_path="/"` and wire lifespan:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

from gdansk import Amber

mcp = FastMCP("FastAPI Example Server", streamable_http_path="/")
amber = Amber(mcp=mcp, views=Path(__file__).parent / "views")
mcp_app = amber(dev=True)

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with mcp_app.router.lifespan_context(mcp_app):
        yield

app = FastAPI(lifespan=lifespan)
app.mount(path="/mcp", app=mcp_app)
```

## PostCSS plugin

Attach plugin:

```python
from gdansk.experimental.postcss import PostCSS

amber = Amber(mcp=mcp, views=views_path, plugins=[PostCSS()])
```

Requirements in `views/`:

- `node_modules/.bin/postcss` must exist
- install with:

```bash
cd views
npm install -D postcss postcss-cli
```

Behavior summary:

- `build`: transforms discovered `.gdansk/**/*.css` once after bundle.
- `watch` in dev: polls CSS outputs and re-runs transform on changes.

## Decision matrix

| Need | Option |
| --- | --- |
| Server-rendered initial HTML for all tools | `Amber(..., ssr=True)` |
| Server-rendered initial HTML for one tool | `@amber.tool(..., ssr=True)` |
| Force client-only rendering for one tool while global SSR is on | `@amber.tool(..., ssr=False)` |
| Dynamic SSR output must not be cached | `Amber(..., cache_html=False)` |
| Shared head metadata across tools | constructor `metadata=` |
| Per-tool title or OG override | `@amber.tool(..., metadata=...)` |
| Running inside existing FastAPI service | mount `mcp_app` + lifespan wrapper |
| Tailwind/PostCSS transform on generated CSS | add `PostCSS()` plugin and CLI deps |

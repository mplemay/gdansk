# Integrations

Use this file when the request goes beyond basic widget wiring. For React widget patterns, see [widgets.md](widgets.md).

## Metadata behavior

`Ship` accepts optional `metadata` using the `Metadata` shape from `gdansk.metadata` (a `TypedDict`).

```python
from pathlib import Path

from gdansk import Ship, Vite
from gdansk.metadata import Metadata

frontend_path = Path(__file__).parent / "views"
meta: Metadata = {
    "title": "Root App",
    "description": "Shared description",
    "openGraph": {"title": "Shared OG"},
}

ship = Ship(vite=Vite(frontend_path), metadata=meta)
```

Per-widget metadata can be passed directly to `@ship.widget(..., metadata=...)`.

Merge semantics for metadata helpers (such as `merge_metadata` in `gdansk.metadata`) are shallow top-level merge when
you combine sources in application code.

## Widget decorator surface

`Ship.widget(...)` supports the following public knobs:

- `name`
- `title`
- `description`
- `annotations`
- `icons`
- `meta`
- `metadata`
- `structured_output`
- `schema` (`"default"` or `"strict"`)

Prefer these public arguments over custom wrapper logic when the request only needs tool metadata or typed output.

### Icons and annotations

```python
from mcp.types import Icon

@ship.widget(
    path=Path("hello/widget.tsx"),
    name="hello",
    title="Hello Widget",
    description="A greeting widget",
    icons=[Icon(src="https://example.com/icon.png", mimeType="image/png")],
)
def hello() -> list[TextContent]: ...
```

### WidgetMeta and CSP

```python
from gdansk import WidgetMeta

@ship.widget(
    path=Path("hello/widget.tsx"),
    name="hello",
    meta=WidgetMeta(
        ui={"visibility": ["model", "app"], "prefers_border": True},
    ),
)
def hello() -> list[TextContent]: ...
```

## Structured output

Use `structured_output=True` when the UI should receive typed data rather than parse text content manually.

```python
from dataclasses import dataclass

from gdansk import Ship, Vite

@dataclass(slots=True, kw_only=True)
class Todo:
    id: str
    title: str
    completed: bool = False

todos: list[Todo] = []

@ship.widget(path=Path("todo/widget.tsx"), name="list-todos", structured_output=True)
def list_todos() -> list[Todo]:
    return list(todos)


mcp = MCPServer(name="Todo Server", lifespan=lifespan)


@mcp.tool(name="add-todo", structured_output=True)
def add_todo(title: str) -> list[Todo]:
    todos.append(Todo(id="1", title=title.strip()))
    return list(todos)
```

Widget tools and plain `@mcp.tool` handlers can share the same `MCPServer` and return typed data. For
React-side consumption, see [widgets.md](widgets.md).

## Custom runtime host or port

The default frontend runtime address is `127.0.0.1:13714`. If you change it, keep Python and Vite in sync.
See [rules/config-sync.md](../rules/config-sync.md) for Incorrect/Correct pairs.

## Vite plugin options

`@gdansk/vite` stays convention-first, but the main frontend directory knobs are explicit:

- `refresh: true` watches nearby Python and Jinja files and triggers a full browser reload during development.
- `buildDirectory` changes the frontend output directory and should match `Vite(..., build_directory=...)`.
- Widget entry files are discovered under `widgets/` relative to the frontend root.
- The plugin provides a default `@` alias to the frontend root.

## Plain MCP tools (no React UI)

Register tools on the same `MCPServer` instance that you pass into `ship.mcp(app=...)`:

```python
mcp = MCPServer(name="My Server", lifespan=lifespan)


@mcp.tool(name="ping")
def ping() -> str:
    return "pong"
```

Use `mcp.add_tool(...)` if you prefer imperative registration.

Register plain tools on the same `MCPServer` passed to `ship.mcp(app=...)` — see the structured output
section above for a multi-tool pattern.

## FastAPI mounting pattern

When embedding the MCP Streamable HTTP app in FastAPI, use `streamable_http_path="/"` on the inner app and wire both
lifespans:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from mcp.server import MCPServer

from gdansk import Ship, Vite

frontend_path = Path(__file__).parent / "views"
ship = Ship(vite=Vite(frontend_path))


@asynccontextmanager
async def mcp_lifespan(app: MCPServer) -> AsyncIterator[None]:
    async with ship.mcp(app=app, watch=True):
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

Run:

```bash
uv sync
uv run fastapi dev main.py
```

To toggle dev vs production watch mode from environment settings:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    production: bool = False

settings = Settings()

@asynccontextmanager
async def mcp_lifespan(app: MCPServer) -> AsyncIterator[None]:
    async with ship.mcp(app=app, watch=not settings.production):
        yield
```

`gdansk` production widgets render inline JS and CSS in the `ui://` HTML resource, so FastAPI only needs to mount the
MCP app.

## Styling and Tailwind

Style widgets with normal frontend tooling in the frontend root (for example PostCSS, Tailwind, or component
libraries). Put Vite-specific setup in `vite.config.ts`, import `@gdansk/vite` there, and keep framework plugins in
that same file. Declare dependencies in `pyproject.toml` under `[belgie.dependencies]`, run `uv run gdansk install`
from the Python project root, and commit the belgie lockfile (`deno.lock`) when it changes.

Example Tailwind dependencies:

```toml
[belgie.dependencies]
tailwindcss = "^4"
"@tailwindcss/vite" = "^4"
postcss = "^8"
```

Component libraries such as shadcn/ui install the same way — add their npm packages to `[belgie.dependencies]`
and configure any required Vite plugins in `vite.config.ts`.

## Decision matrix

| Need | Option |
| --- | --- |
| Shared head metadata across widgets | constructor `metadata=` (`gdansk.metadata.Metadata`) |
| Per-widget title or OG override | `@ship.widget(..., metadata=...)` |
| Typed tool responses for the UI | `@ship.widget(..., structured_output=True)` |
| Tool icons and descriptions | `@ship.widget(..., icons=..., title=..., description=...)` |
| CSP and visibility control | `@ship.widget(..., meta=WidgetMeta(...))` |
| Running inside existing FastAPI service | mount `mcp_app` + nested lifespan |
| Tool without a React surface | `@mcp.tool` / `add_tool` on `MCPServer` |
| Production deployment | [production.md](production.md) |

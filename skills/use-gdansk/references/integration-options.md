# Integration Options

Use this file when the request goes beyond basic widget wiring.

## Metadata behavior

`Ship` accepts optional `metadata` using the `Metadata` shape from `gdansk.metadata` (a `TypedDict`).

```python
from gdansk import Ship, Vite
from gdansk.metadata import Metadata

meta: Metadata = {
    "title": "Root App",
    "description": "Shared description",
    "openGraph": {"title": "Shared OG"},
}

ship = Ship(vite=Vite(views_path), metadata=meta)
```

Per-widget metadata can be passed directly to `@ship.widget(..., metadata=...)`.

Merge semantics for metadata helpers (such as `merge_metadata` in `gdansk.metadata`) are shallow top-level merge when
you combine sources in application code.

## Widget decorator surface

`Ship.widget(...)` supports the following public knobs that matter for repo integrations:

- `name`
- `title`
- `description`
- `annotations`
- `icons`
- `meta`
- `metadata`
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
from gdansk import Ship, Vite

ship = Ship(vite=Vite(views_path, host="127.0.0.1", port=14000))
```

```ts
export default defineConfig({
  plugins: [gdansk({ host: "127.0.0.1", port: 14000, refresh: true }), react()],
});
```

## Vite plugin options

`@gdansk/vite` stays convention-first, but the main frontend directory knobs are now explicit:

- `refresh: true` watches nearby Python and Jinja files and triggers a full browser reload during development.
- `buildDirectory` changes the frontend output directory and should match `Vite(..., build_directory=...)`.
- Widget entry files are discovered under `widgets/` relative to the frontend package root.
- The plugin provides a default `@` alias to the frontend package root.

Example:

```python
ship = Ship(
    vite=Vite(
        views_path,
        build_directory="public/ui",
    ),
)
```

```ts
export default defineConfig({
  plugins: [
    gdansk({
      buildDirectory: "public/ui",
      refresh: true,
    }),
    react(),
  ],
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

from gdansk import Ship, Vite

frontend_path = Path(__file__).parent / "frontend"
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
app.mount(path=ship.assets_path, app=ship.assets)
app.mount(path="/mcp", app=mcp_app)
```

`gdansk` production widgets expect hydration assets at `ship.assets_path`. With the default build directory, mount
`ship.assets` at `/dist`.

The default production output is:

- `dist/manifest.json` for the standard Vite manifest
- `dist/gdansk-manifest.json` for gdansk's runtime manifest
- `dist/<widget>/client.js` and `dist/<widget>/client.css` for stable widget entry assets
- `dist/assets/*` for shared hashed assets and chunks

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

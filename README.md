# Gdansk: React Frontends for Python MCP Servers

> [!WARNING]
> This project is currently in beta. The APIs are subject to change leading up to v1.0. The v1.0 release will
> coincide with the v2.0 release of the [python mcp sdk](https://github.com/modelcontextprotocol/python-sdk)

## Installation

```bash
uv add gdansk
```

## Skill for Coding Agents

If you use coding agents such as Claude Code or Cursor, add the gdansk skills to your repository:

```shell
npx skills add mplemay/gdansk
```

Then use:

- `$use-gdansk` to bootstrap gdansk in a new repo or add another widget to an existing integration.
- `$debug-gdansk` to diagnose widget path, bundling, render, and runtime failures in an existing gdansk setup.

## Compatibility

- Python: `gdansk` currently requires `>=3.12,<3.15`.
- Frontend package: use an ESM package with `@gdansk/vite`, `vite`, `@vitejs/plugin-react`, `react`, `react-dom`,
  and `@modelcontextprotocol/ext-apps`. Inertia page mode targets `@inertiajs/react@3.0.3`.
- Runtime tooling: gdansk starts the frontend through `uv run deno ...`. If you run frontend package scripts directly,
  the published `@gdansk/vite` package currently declares Node `>=22`.

## Examples

- **[FastAPI](examples/fastapi):** Mounting the MCP app inside an existing FastAPI service.
- **[inertia](examples/inertia):** Ship-backed Inertia pages for FastAPI with `gdanskPages()`.
- **[get-time](examples/get-time):** Small copyable widget example for first-time adoption in another repo.
- **[production](examples/production):** Minimal production-rendered and hydrated widget example with a single tool.
- **[shadcn](examples/shadcn):** Multi-tool todo app with `structured_output=True` and `shadcn/ui`.

## Inertia Pages

`Ship` can serve convention-driven Inertia v3 pages directly: the first request returns an HTML shell, follow-up
requests use the Inertia JSON protocol, and production assets still come from `ship.assets`.

Page mode is convention-driven. Put the root page at `app/page.tsx`, nested pages at `app/**/page.tsx`, and
co-located layouts at `app/**/layout.tsx`. Decorate matching routes with `@ship.page()` to infer the component from
the route path, or use an explicit id like `@ship.page("dashboard/reports")` when the backend route and frontend page
key intentionally differ.

For FastAPI pages, decorate a route with `@ship.page(...)`, return a Pydantic model or mapping, and run the frontend
with `ship.lifespan(...)`. Page routes may also return `None` for empty props or an `InertiaResponse` such as
`page.location("/#activity")`. Pass `inertia=Inertia(...)` to `Ship` to configure page settings such as a custom root
id, explicit version, or default encrypted history.

```python
from pydantic import BaseModel, Field

from gdansk import Defer, Inertia, Merge, Metadata, Ship, Vite


class HomeProps(BaseModel):
    activity: Defer[list[str]]
    announcements: Merge[list[dict[str, str]]]
    headline: str
    updated_at: str = Field(serialization_alias="updatedAt")


ship = Ship(vite=Vite("frontend"), inertia=Inertia(id="app"))


@app.get("/")
@ship.page(metadata=Metadata(title="Home"))
async def home() -> HomeProps:
    return HomeProps(
        activity=Defer(value=load_activity, group="activity"),
        announcements=Merge(value=load_announcements(), match_on="id"),
        headline="FastAPI + Inertia",
        updated_at="May 5, 2026",
    )
```

If a rendered route needs imperative page control for flash, history flags, or per-request shared props, combine the
decorator with `Depends(ship.page)`, mutate the injected page, and return props from the route.

Pair the backend with `gdanskPages()` in your frontend `vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { gdanskPages } from "@gdansk/vite";

export default defineConfig({
  plugins: [gdanskPages({ refresh: true }), react()],
});
```

For a full FastAPI example with validation errors, flash messages, deferred props, once props, merge helpers, scroll
props, and fragment redirects, see
[`examples/inertia`](examples/inertia).

The backend prop wrappers are close to the official non-SSR Inertia protocol:

- `Prop(value=...)` is the advanced escape hatch for combining prop behaviors.
- `OptionalProp(value=...)`, `Always(value=...)`, and `Defer(value=..., group=...)` control eager vs partial/deferred
  loading.
- `Once(value=..., key=...)` and `page.share_once(...)` emit `onceProps` so the client can reuse previously loaded data.
- `Merge(value=..., match_on=...)`, `Merge(value=..., deep=True, match_on=...)`, and
  `Merge(value=..., mode="prepend")` emit merge metadata.
- `Scroll(value=...)` emits both merge metadata and `scrollProps` for infinite-scroll style payloads.
- `page.encrypt_history(...)`, `page.clear_history()`, and `page.redirect(..., preserve_fragment=True)` control history
  and redirect behavior.

```python
from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel

from gdansk import InertiaPage, Merge, Once, OptionalProp, Scroll

type PageDependency = Annotated[InertiaPage, Depends(ship.page)]


class DashboardProps(BaseModel):
    announcements: Merge[list[dict[str, object]]]
    conversation: Merge[dict[str, object]]
    feed: Scroll[dict[str, object]]
    profile: Once[object]
    stats: OptionalProp[object]


@app.get("/")
@ship.page()
async def home(page: PageDependency) -> DashboardProps:
    page.share_once(sessionToken=load_session_token)

    return DashboardProps(
        announcements=Merge(value=load_announcements(), match_on="id"),
        conversation=Merge(value=load_conversation(), deep=True, match_on="messages.id"),
        feed=Scroll(
            value=load_feed(),
            items_path="items",
            current_page_path="pagination.current",
            next_page_path="pagination.next",
            previous_page_path="pagination.previous",
            page_name="feed_page",
        ),
        profile=Once(value=load_profile, key="shared-profile"),
        stats=OptionalProp(value=load_stats),
    )
```

## Quick Start

Here's a complete example showing how to build a simple greeting tool with a React UI:

**Project Structure:**

```text
my-mcp-server/
├── server.py
└── frontend/
    ├── package.json
    ├── vite.config.ts
    └── widgets/
        └── hello/
            └── widget.tsx
```

The `frontend` folder name is only an example. Pass any frontend package root to `Vite(...)`.
That frontend package owns its own `vite.config.ts`; import `@gdansk/vite` there alongside any framework plugins.

**server.py:**

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from mcp.server import MCPServer
from mcp.types import TextContent
from starlette.middleware.cors import CORSMiddleware

from gdansk import Ship, Vite

frontend_path = Path(__file__).parent / "frontend"
ship = Ship(vite=Vite(frontend_path))


@ship.widget(path=Path("hello/widget.tsx"), name="greet")
def greet(name: str) -> list[TextContent]:
    """Greet someone by name."""
    return [TextContent(type="text", text=f"Hello, {name}!")]


@asynccontextmanager
async def lifespan(mcp: MCPServer) -> AsyncIterator[None]:
    async with ship.lifespan(mcp=mcp, watch=True):
        yield


mcp = MCPServer(name="Hello World Server", lifespan=lifespan)


def main() -> None:
    app = mcp.streamable_http_app()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount(path=ship.assets_path, app=ship.assets)
    uvicorn.run(app, port=3000)


if __name__ == "__main__":
    main()
```

**frontend/widgets/hello/widget.tsx:**

```tsx
import { useApp } from "@modelcontextprotocol/ext-apps/react";
import { useState } from "react";

export default function App() {
  const [name, setName] = useState("");
  const [greeting, setGreeting] = useState("");

  const { app, error } = useApp({
    appInfo: { name: "Greeter", version: "1.0.0" },
    capabilities: {},
  });

  if (error) return <div>Error: {error.message}</div>;
  if (!app) return <div>Connecting...</div>;

  return (
    <main>
      <h2>Say Hello</h2>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Enter your name..."
      />
      <button
        onClick={async () => {
          const result = await app.callServerTool({
            name: "greet",
            arguments: { name },
          });
          const text = result.content?.find((c) => c.type === "text");
          if (text && "text" in text) setGreeting(text.text);
        }}
      >
        Greet Me
      </button>
      {greeting && <p>{greeting}</p>}
    </main>
  );
}
```

**frontend/package.json:**

```json
{
  "name": "my-mcp-frontend",
  "private": true,
  "type": "module",
  "dependencies": {
    "@gdansk/vite": "^0.1.0",
    "@modelcontextprotocol/ext-apps": "^1.5.0",
    "@vitejs/plugin-react": "^6.0.1",
    "react": "^19.2.5",
    "react-dom": "^19.2.5",
    "vite": "^8.0.8"
  },
  "devDependencies": {
    "@types/react": "^19.2.14",
    "@types/react-dom": "^19.2.3"
  }
}
```

**frontend/vite.config.ts:**

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import gdansk from "@gdansk/vite";

export default defineConfig({
  plugins: [gdansk({ refresh: true }), react()],
});
```

`@gdansk/vite` now provides a default `@` alias that points at the frontend package root, so you only need a manual
alias when you want `@` to resolve somewhere else. Use `refresh: true` to trigger full browser reloads when nearby
Python or Jinja files change during development.

For widget-based MCP apps, `ship.lifespan(..., watch=...)` controls how the frontend is prepared:

- **`watch=True`** — runs the Vite dev server in the background with React refresh; JS/CSS load from the Vite origin.
- **`watch=False`** (default) — runs `vite build` on startup, then serves static hydration assets and the gdansk
  manifest from `ship.assets`.
- **`watch=None`** — skips Vite/Deno entirely and loads an existing `gdansk-manifest.json` under the assets directory.
  Use this when assets are prebuilt (for example in CI) to avoid cold-start build cost.

If you need a non-default build output directory, keep the Vite plugin and Python runtime aligned. Widget sources
always live under `widgets/` at the frontend package root (`Vite(root=...)` / Vite `root`).

```python
ship = Ship(
    vite=Vite(
        Path(__file__).parent / "frontend",
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

Production widgets load their hydration assets from `ship.assets_path`. Mount `ship.assets` at that path on the
public app; with the default settings this is `/dist`.

The default production output now mirrors Vite/Laravel conventions more closely:

- standard Vite manifest: `dist/manifest.json`
- gdansk runtime manifest: `dist/gdansk-manifest.json`
- stable widget entries: `dist/<widget>/client.js` and `dist/<widget>/client.css`
- shared hashed assets and chunks: `dist/assets/*`

If your MCP client renders widget HTML on a different origin, pass `base_url` to `Ship` so production asset URLs point
back to your public app instead of the client host:

```python
ship = Ship(vite=Vite(Path(__file__).parent / "frontend"), base_url="https://example.com")
```

If you want a different dev runtime host or port, configure both sides explicitly:

```python
from gdansk import Ship, Vite

ship = Ship(vite=Vite(Path(__file__).parent / "frontend", host="127.0.0.1", port=14000))
```

```ts
export default defineConfig({
  plugins: [gdansk({ host: "127.0.0.1", port: 14000, refresh: true }), react()],
});
```

Install the frontend package dependencies from `frontend/` after editing them:

```bash
cd frontend
uv run deno install
```

Gdansk mounts your default export into `#root` automatically and wraps it with `React.StrictMode`.

Run the server with `uv run python server.py`, configure it in your MCP client (like Claude Desktop), and you'll have
an interactive greeting tool ready to use.

## Why Use Gdansk?

1. **Python Backend, React Frontend** — Use familiar technologies you already know. Write your logic in Python with type
   hints, build your UI in React/TypeScript. No need to learn a new framework-specific language.

2. **Built for MCP** — Composes with `MCPServer` from the official Python SDK: register widget tools and HTML resources
   via `Ship`, wire them in with `ship.lifespan(mcp=...)`, and integrate with Claude Desktop and other MCP clients.

3. **Fast bundling with Rolldown** — The Rolldown bundler processes your TypeScript/JSX automatically. Hot-reload in
   development mode means you see changes instantly without manual rebuilds.

4. **Type-Safe** — Full type safety across the stack. Python type hints on the backend, TypeScript on the frontend, with
   automatic type checking via ruff and TypeScript compiler.

5. **Developer-Friendly** — Simple decorator API (`@ship.widget()`), automatic resource registration, dev mode on
   `ship.lifespan(...)`, and comprehensive error messages. Get started in minutes, not hours.

6. **Production Ready** — Comprehensive test suite covering Python 3.12+ across Linux, macOS, and Windows. Used in
   production MCP servers with proven reliability.

## Credits

Gdansk builds on the shoulders of giants:

- **[Model Context Protocol](https://modelcontextprotocol.io/)** — Official MCP documentation
- **[@modelcontextprotocol/ext-apps](https://www.npmjs.com/package/@modelcontextprotocol/ext-apps)** — React hooks for
  MCP apps
- **[Rolldown](https://rolldown.rs/)** — Fast JavaScript bundler
- **[mcp/python-sdk](https://github.com/modelcontextprotocol/python-sdk)** — Python SDK for MCP server development
- **[Deno](https://deno.com/)** — JavaScript/TypeScript runtime used by the embedded Deno tooling

Special thanks to the Model Context Protocol team at Anthropic for creating the MCP standard and the
`@modelcontextprotocol/ext-apps` package.

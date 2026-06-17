# Production Deployment

Use this file when deploying gdansk widgets beyond local development — CI builds, Docker images, or
production servers without a Vite dev server.

## Watch modes in production

| Mode | When to use | Build step |
| --- | --- | --- |
| `watch=False` | Server builds assets on startup | Automatic `vite build` in lifespan |
| `watch=None` | Assets prebuilt in CI/image | Run `uv run gdansk build` before deploy |

### `watch=False` (build on startup)

```python
@asynccontextmanager
async def lifespan(app: MCPServer) -> AsyncIterator[None]:
    async with ship.mcp(app=app, watch=False):
        yield
```

The server runs `vite build` during lifespan startup, then serves static assets from `ship.assets`.
Use when you want a single deployable artifact without a separate build step in CI. There is no separate
JS runtime server in production — only static `dist/` assets served via `ship.assets`.

### `watch=None` (prebuilt assets)

```python
@asynccontextmanager
async def lifespan(app: MCPServer) -> AsyncIterator[None]:
    async with ship.mcp(app=app, watch=None):
        yield
```

Skips the frontend build toolchain entirely. Loads existing `gdansk-manifest.json` from the assets directory.
Use in CI/CD or Docker when you build assets in a prior step:

```bash
uv run gdansk build
# deploy dist/ alongside the Python server
```

## Expected `dist/` layout

After a production build:

```text
<frontend-root>/dist/
├── manifest.json              # standard Vite manifest
├── gdansk-manifest.json       # gdansk runtime manifest
├── <widget>/client.js         # stable widget entry
├── <widget>/client.css        # optional widget styles
└── assets/*                   # hashed chunks
```

Verify after build:

```bash
find <frontend-root>/dist -type f | sort
```

## Asset mounting checklist

Production widgets load hydration assets from `ship.assets_path` (default `/dist`).

- [ ] `ship.assets` mounted at `ship.assets_path` on the public HTTP app
- [ ] `dist/gdansk-manifest.json` exists (for `watch=False` or `watch=None`)
- [ ] `dist/<widget>/client.js` exists for each registered widget
- [ ] CORS configured if the MCP client accesses the server from a different origin

```python
app = mcp.streamable_http_app()
app.mount(path=ship.assets_path, app=ship.assets)
```

With default settings, mount at `/dist`.

## `base_url` for cross-origin clients

When the MCP client renders widget HTML on a different origin, asset URLs in the HTML must point back to
your server:

```python
ship = Ship(
    vite=Vite(frontend_path),
    base_url="https://api.example.com",
)
```

Without `base_url`, production asset URLs may resolve against the client host instead of your server.

## CI pattern

Typical CI pipeline:

```bash
uv sync
uv run gdansk install
uv run gdansk build
uv run gdansk doctor
uv run pytest
```

Deploy with `watch=None` and include the built `dist/` directory in the image or artifact.

## Development vs production

| Concern | Development | Production |
| --- | --- | --- |
| `watch` | `True` | `False` or `None` |
| JS/CSS source | Vite dev server origin | Static `dist/` via `ship.assets` |
| Hot reload | HMR + `refresh: true` | N/A |
| Build command | Automatic (via `watch=True`) | `gdansk build` or startup build |

For local development, always use `watch=True` with `gdansk({ refresh: true })`.

## Troubleshooting production

| Symptom | Check |
| --- | --- |
| Widget HTML loads but JS fails | `ship.assets` mount; `dist/<widget>/client.js` exists |
| `gdansk-manifest.json` missing | Run `gdansk build` or use `watch=False` |
| Assets 404 on client | `base_url` set correctly; CORS headers |
| Stale widget after deploy | Rebuild `dist/`; confirm `watch=None` reads new manifest |

For detailed error mapping, see [troubleshooting.md](troubleshooting.md).

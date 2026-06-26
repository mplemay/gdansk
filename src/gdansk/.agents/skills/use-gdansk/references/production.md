# Production Deployment

Use this file when deploying gdansk widgets beyond local development — CI builds, Docker images, or
production servers without a Vite dev server.

## Watch modes in production

| Mode | When to use | Build step |
| --- | --- | --- |
| `watch=False` | Server builds widgets on startup | Automatic `vite build` in lifespan |
| `watch=None` | Widgets already built in-process or in CI/image | Run `uv run gdansk build` before deploy if needed |

### `watch=False` (build on startup)

```python
@asynccontextmanager
async def lifespan(app: MCPServer) -> AsyncIterator[None]:
    async with ship.mcp(app=app, watch=False):
        yield
```

The server runs `vite build` during lifespan startup, then caches the inline widget bundles in memory. Each `ui://`
resource returns HTML with inline `<style>` and `<script type="module">` tags. Use this when you want a single
deployable artifact without a separate build step in CI.

### `watch=None` (prebuilt widgets)

```python
@asynccontextmanager
async def lifespan(app: MCPServer) -> AsyncIterator[None]:
    async with ship.mcp(app=app, watch=None):
        yield
```

Skips the frontend build toolchain entirely. Uses a cached build result if one is already available; otherwise it builds
on demand. Use in CI/CD or Docker when you want to avoid a second startup build:

```bash
uv run gdansk build
# no manifest artifact is required alongside the Python server
```

## Expected `dist/` layout

After a production build:

```text
<frontend-root>/dist/
└── (cached in memory)         # gdansk runtime inline widget bundles
```

Verify after build:

```bash
find <frontend-root>/dist -type f | sort
```

## Production checklist

- [ ] Each widget has `inline.script` and `inline.styles`
- [ ] No `dist/<widget>/client.js`, `dist/<widget>/client.css`, or `dist/assets/*` files are required
- [ ] CORS configured if the MCP client accesses the server from a different origin

Imported assets in the Vite graph are inlined as data URLs. Files in Vite `public/` and runtime network fetches remain
application concerns and are not folded into the widget HTML.

## `base_url` for cross-origin clients

When the MCP client renders widget HTML on a different origin, pass the public server origin through `base_url` so
widget metadata can describe the server side of the integration:

```python
ship = Ship(
    vite=Vite(frontend_path),
    base_url="https://api.example.com",
)
```

Inline production JS/CSS do not need asset URLs, so `base_url` is not a static-file mount substitute.

## CI pattern

Typical CI pipeline:

```bash
uv sync
uv run gdansk lock
uv run gdansk build
uv run gdansk doctor
uv run pytest
```

Deploy with `watch=None` and keep the build result available in memory or rebuild on startup.

## Development vs production

| Concern | Development | Production |
| --- | --- | --- |
| `watch` | `True` | `False` or `None` |
| JS/CSS source | Vite dev server origin | Inline payloads from the cached build result |
| Hot reload | HMR + `refresh: true` | N/A |
| Build command | Automatic (via `watch=True`) | `gdansk build` or startup build |

For local development, always use `watch=True` with `gdansk({ refresh: true })`.

## Troubleshooting production

| Symptom | Check |
| --- | --- |
| Widget HTML loads but JS fails | Rendered HTML contains an inline `<script type="module">` |
| Build result missing | Run `gdansk build` or use `watch=False` |
| Assets 404 on client | The widget likely references `public/` or fetches network resources at runtime |
| Stale widget after deploy | Rebuild `dist/`; confirm `watch=None` reads new manifest |

For detailed error mapping, see [troubleshooting.md](troubleshooting.md).

# Architecture and Decision Guide

Use this file when choosing between abstractions, watch modes, or understanding how gdansk pieces fit together.

## Mental model

Gdansk bridges three layers:

1. **Python MCP server** — `MCPServer` from the official MCP Python SDK.
2. **Ship orchestrator** — registers each widget as an MCP tool + HTML resource, manages frontend lifecycle.
3. **React frontend** — widgets in `widgets/*/widget.tsx`, bundled by `@gdansk/vite`.

```text
Python                          Frontend root
──────                          ─────────────
Ship                            vite.config.ts + @gdansk/vite
  └─ Vite(root)                   └─ widgets/<name>/widget.tsx
  └─ @ship.widget(...)                  └─ dist/gdansk-manifest.json
  └─ ship.mcp(app, watch)               └─ dist/gdansk-manifest.json
       │
       ├─ registers MCP tool (Python function)
       ├─ registers HTML resource (ui://<widget-key>)
       └─ links tool meta["ui"]["resourceUri"] → resource

MCP client
──────────
  ├─ reads ui:// resource → rendered HTML with inline JS/CSS
  └─ React widget calls tool via useApp().callServerTool(...)
```

## What `@ship.widget` registers

For each decorated Python function, gdansk creates:

1. **MCP tool** — the Python function, with optional `structured_output`, `schema`, icons, annotations.
2. **MCP resource** — HTML page at `ui://<widget-key>`, `mime_type="text/html;profile=mcp-app"`.
3. **Tool metadata** — `meta["ui"]["resourceUri"]` links the tool to the resource.
4. **Rendered HTML** — Jinja shell with scripts, CSS, metadata, and `#root` mount point.

See [path-contract.md](path-contract.md) for how `path=` maps to `ui://` URIs.

## Watch mode decision tree

```text
Need live HMR during development?
├── Yes → ship.mcp(app=app, watch=True)
│         Vite dev server runs in background; JS/CSS load from Vite origin.
└── No → Assets prebuilt in CI or image?
    ├── Yes → ship.mcp(app=app, watch=None)
    │         Skips Vite; loads existing gdansk-manifest.json from dist/.
    └── No → ship.mcp(app=app, watch=False)   [default]
              Runs vite build on startup; renders inline bundles from the manifest.
```

| `watch` | Behavior | Use when |
| --- | --- | --- |
| `True` | Vite dev server with HMR | Local development |
| `False` | Build on startup, render inline bundles from `dist/gdansk-manifest.json` | Production without prebuilt assets |
| `None` | Skip build, load existing manifest | CI/CD images with prebuilt `dist/` |

For production deployment details, see [production.md](production.md).

## Key types

| Type | Role |
| --- | --- |
| `Ship` | Central orchestrator; widget registration, HTML resource rendering, MCP wiring |
| `Vite` | Python-side frontend config: root, host, port, build_directory |
| `@gdansk/vite` | Vite plugin; discovers widgets, emits `gdansk-manifest.json` |
| `Metadata` | Page metadata (`gdansk.metadata.Metadata` TypedDict) |
| `WidgetMeta` | Tool/resource metadata (CSP, visibility, OpenAI-specific fields) |

## `base_url` for cross-origin rendering

When the MCP client renders widget HTML on a different origin than your server, pass `base_url` to `Ship` so widget
metadata can describe the public server origin:

```python
ship = Ship(
    vite=Vite(frontend_path),
    base_url="https://example.com",
)
```

## gdansk dependency model

Frontend npm/JSR packages live in `[gdansk.dependencies]` tables in `pyproject.toml` — not in a `package.json`
at the app frontend root.

```toml
[gdansk.dependencies]
react = "^19"
vite = "8.0.8"
"@gdansk/vite" = "^0.1.0"

[gdansk.commands]
lint = ["oxlint", "--fix"]
```

- Add dependencies with `uv run gdansk add` or lock manual edits with `uv run gdansk lock`.
- gdansk writes `deno.lock` at the Python project root and creates temporary Belgie environments for execution.
- Run builds via `uv run gdansk build` / `uv run gdansk dev`, not raw `vite` commands.
- `package.json` exists only in separately published packages like `@gdansk/vite` itself.

## Integration patterns

| Pattern | Reference |
| --- | --- |
| Standalone MCP server + uvicorn | [quickstart.md](quickstart.md) |
| FastAPI embedding | [integrations.md](integrations.md) |
| Plain MCP tools (no React UI) | [integrations.md](integrations.md) |
| Multi-tool app with structured output | [integrations.md](integrations.md) |
| Production / CI | [production.md](production.md) |

## Config alignment checklist

Before running, confirm:

- [ ] `Vite(...)` points at frontend root (not `widgets/`)
- [ ] `Vite(host, port, build_directory)` matches `gdansk({ host, port, buildDirectory })`
- [ ] `@ship.widget(path=...)` is relative to `widgets/` without `widgets/` prefix
- [ ] Production deploy includes `dist/gdansk-manifest.json`
- [ ] `[gdansk.dependencies]` installed via `uv run gdansk lock`

For Incorrect/Correct pairs, see [rules/config-sync.md](../rules/config-sync.md) and
[rules/path-contract.md](../rules/path-contract.md).

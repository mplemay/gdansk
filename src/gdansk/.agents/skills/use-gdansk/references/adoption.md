# Adoption

Use this file when the task is to make gdansk work cleanly in another repository.

## Recommended bootstrap

```bash
uv add gdansk
uv run gdansk init
uv run gdansk lock
uv run gdansk doctor
```

`gdansk init` scaffolds `src/<package>/views/` as the frontend root. For manual layout, see
[quickstart.md](quickstart.md) Path B.

## Compatibility

- Python: `gdansk` currently requires `>=3.12,<3.15`.
- Frontend dependencies:
  - Declared in `[gdansk.dependencies]` and grouped tables such as `[gdansk.dependencies.dev]`.
  - React 19 and Vite 8 in the current examples and published plugin package.
- Runtime tooling:
  - gdansk runs Vite internally through Belgie `Environment`, `Runtime`, and `Command`.
  - `[gdansk.commands]` is only for optional user-defined package commands.

## Minimum external-repo structure

After `gdansk init`:

```text
my-mcp-server/
├── pyproject.toml
└── src/<package>/
    ├── __main__.py
    └── views/
        ├── vite.config.ts
        └── widgets/
            └── hello/
                └── widget.tsx
```

For manual adoption with a custom frontend dir name:

```text
my-mcp-server/
├── pyproject.toml
├── server.py
└── frontend/
    ├── vite.config.ts
    └── widgets/
        └── hello/
            └── widget.tsx
```

The frontend directory name is only an example. Pass any frontend root to `Vite(...)`.

## Python dependency baseline

Add gdansk to the Python project:

```bash
uv add gdansk
```

If the repo also serves the app over HTTP, add the HTTP framework you need separately (`uvicorn`, `fastapi`, and so
on).

## Frontend dependency baseline

The Python project should declare frontend dependencies in `pyproject.toml`:

```toml
[gdansk.dependencies]
"@gdansk/vite" = "^0.1.0"
"@modelcontextprotocol/ext-apps" = "^1.5.0"
"@vitejs/plugin-react" = "^6.0.2"
react = "^19"
react-dom = "^19"
vite = "8.0.14"

[gdansk.dependencies.dev]
"@types/react" = "^19"
"@types/react-dom" = "^19"

[gdansk.commands]
lint = ["oxlint", "--fix"]
```

Prefer `gdansk add` for additions. After manual dependency changes in `pyproject.toml`:

```bash
uv run gdansk add react "^19"
uv run gdansk lock
```

If the repo tracks the gdansk lockfile (`deno.lock`), keep it at the Python project root and in sync with the edited
dependencies.

## Public API checklist

- Construct `Ship` with the frontend root: `Ship(vite=Vite(Path(...)))`.
- Register widget tools with `@ship.widget(...)`.
- Use `path=Path("<widget>/widget.tsx")` or `.jsx`, relative to `widgets/`.
- Enter `async with ship.mcp(app=app, watch=...)` inside the `MCPServer` lifespan (`watch=True` for Vite dev,
  `watch=False` to build on startup, `watch=None` when widgets are prebuilt).
- Import `@gdansk/vite` inside the frontend root's `vite.config.ts`.
- Rely on the plugin's default `@` alias before adding a manual one.
- Prefer `gdansk({ refresh: true })` when backend file changes should reload the browser during development.
- If you customize the build output directory, keep `Vite(Path(...), build_directory=...)` aligned with
  `gdansk({ buildDirectory: ... })`.

## Before finishing

Run validation:

```bash
uv run gdansk doctor
```

Then confirm:

- The server starts with no widget registration errors.
- Frontend output includes `<frontend-root>/dist/gdansk-manifest.json`.
- The UI resource renders and contains inline JS/CSS.
- The widget can call the intended MCP tool.

For a minimal working layout and run commands, see [quickstart.md](quickstart.md).
For multi-tool and styling patterns, see [integrations.md](integrations.md) and [widgets.md](widgets.md).

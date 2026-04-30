# Adoption checklist

Use this file when the task is to make gdansk work cleanly in another repository.

## Compatibility

- Python: `gdansk` currently requires `>=3.12,<3.15`.
- Frontend package:
  - ESM package with `"type": "module"`.
  - React 19 and Vite 8 in the current examples and published plugin package.
- Runtime tooling:
  - gdansk shells out through `uv run deno ...` when it starts the frontend runtime or production build.
  - If the repo uses package scripts directly, the published `@gdansk/vite` package currently declares Node `>=22`.

## Minimum external-repo structure

```text
my-mcp-server/
├── pyproject.toml
├── server.py
└── frontend/
    ├── package.json
    ├── vite.config.ts
    └── widgets/
        └── hello/
            └── widget.tsx
```

The `frontend/` directory name is only an example. Pass any frontend package root to `Vite(...)`.

## Python dependency baseline

Add gdansk to the Python project:

```bash
uv add gdansk
```

If the repo also serves the app over HTTP, add the HTTP framework you need separately (`uvicorn`, `fastapi`, and so
on).

## Frontend dependency baseline

The frontend package should declare at least:

```json
{
  "type": "module",
  "dependencies": {
    "@gdansk/vite": "^0.1.0",
    "@modelcontextprotocol/ext-apps": "^1.5.0",
    "@vitejs/plugin-react": "^6.0.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "vite": "^8.0.0"
  },
  "devDependencies": {
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0"
  }
}
```

After dependency changes inside the frontend package:

```bash
cd frontend
uv run deno install
```

If the repo tracks `deno.lock`, keep it in sync with the edited dependencies.

## Public API checklist

- Construct `Ship` with the frontend package root: `Ship(vite=Vite(Path(...)))`.
- Register widget tools with `@ship.widget(...)`.
- Use `path=Path("<widget>/widget.tsx")` or `.jsx`, relative to `widgets/`.
- Enter `async with ship.lifespan(app=mcp, watch=...)` inside the `MCPServer` lifespan (`watch=True` for Vite dev,
  `watch=False` to build on startup, `watch=None` when assets are prebuilt).
- Import `@gdansk/vite` inside the frontend package's `vite.config.ts`.
- Rely on the plugin's default `@` alias before adding a manual one.
- Prefer `gdansk({ refresh: true })` when backend file changes should reload the browser during development.
- If you customize the build output directory, keep `Vite(Path(...), build_directory=...)` aligned with
  `gdansk({ buildDirectory: ... })`.

## Before finishing

- Confirm the server starts with no widget registration errors.
- Confirm frontend output appears under `<frontend-package>/dist/`.
- Confirm the UI resource renders and the client script is present.
- Confirm the widget can call the intended MCP tool.

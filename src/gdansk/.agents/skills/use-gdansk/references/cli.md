# CLI Reference

Gdansk ships a CLI for project setup, dependency management, and frontend task running. Always invoke it via
`uv run gdansk` from the Python project root.

## Global flags

| Flag | Applies to | Purpose |
| --- | --- | --- |
| `-C`, `--project` | install, lock, update, build, dev, run, scripts, doctor | Project root containing `pyproject.toml` with `[belgie]` configuration |
| `-F`, `--frontend` | build, dev, run, doctor | Frontend root override (default: auto-discovered `src/<package>/views`) |

Pass extra arguments to belgie scripts after `--`:

```bash
uv run gdansk dev -- --host 0.0.0.0
```

## Frontend auto-discovery

The CLI resolves the frontend root as `src/<package>/views` by:

1. Reading `[project.scripts]` entry points to identify the Python package name.
2. Falling back to a single `src/*/views` directory when unambiguous.
3. Failing with an error when ambiguous — pass `-F/--frontend` explicitly.

## Commands

### `gdansk init`

Scaffold a minimal gdansk MCP app.

```bash
uv run gdansk init
uv run gdansk init --path ./my-server
uv run gdansk init --package my_mcp_server --force
```

| Flag | Purpose |
| --- | --- |
| `--path` | Directory to initialize (default: current directory) |
| `--package` | Python package name under `src/` (default: normalized `[project].name`) |
| `--force` | Overwrite existing scaffold files and belgie tables |
| `--no-install` | Skip post-init lockfile generation |

Creates:

```text
<path>/
├── pyproject.toml          # [belgie.dependencies] and [belgie.scripts] appended
└── src/<package>/
    ├── __init__.py
    ├── __main__.py         # Ship + MCPServer + uvicorn
    └── views/              # frontend root (CLI default name)
        ├── vite.config.ts
        └── widgets/hello/widget.tsx
```

Post-init steps printed by the CLI:

```bash
uv run gdansk install
uv run gdansk dev
uv run python -m <package>
```

### `gdansk install`

Install `[belgie.dependencies]` and write the belgie lockfile (`deno.lock`) at the project root.

```bash
uv run gdansk install
uv run gdansk install --no-dev
uv run gdansk install --lock-only
```

| Flag | Purpose |
| --- | --- |
| `--no-dev` | Skip `[belgie.dependencies.dev]` |
| `--lock-only` | Update the belgie lockfile (`deno.lock`) without caching packages |

Run after every change to `[belgie.dependencies]` tables.

### `gdansk lock`

Update the belgie lockfile (`deno.lock`) without installing packages.

```bash
uv run gdansk lock
uv run gdansk lock --no-dev
```

### `gdansk update`

Update `[belgie.dependencies]` packages.

```bash
uv run gdansk update
uv run gdansk update react vite --latest
uv run gdansk update --lock-only
```

| Flag | Purpose |
| --- | --- |
| `packages` | Optional package names to update |
| `--no-dev` | Skip `[belgie.dependencies.dev]` |
| `--latest` | Update to latest versions |
| `--lock-only` | Update lockfile without caching packages |

### `gdansk build`

Run the `[belgie.scripts].build` entry (typically `vite build`).

```bash
uv run gdansk build
uv run gdansk build -F src/my_pkg/views
```

### `gdansk dev`

Run the `[belgie.scripts].dev` entry (typically `vite`).

```bash
uv run gdansk dev
uv run gdansk dev --host 127.0.0.1 --port 14000
```

| Flag | Purpose |
| --- | --- |
| `--host` | Dev server host (default: `127.0.0.1`) |
| `--port` | Dev server port (default: `13714`) |

Prefer `ship.mcp(watch=True)` for integrated dev; use `gdansk dev` when testing the frontend in isolation.

### `gdansk run <script>`

Run any `[belgie.scripts]` entry.

```bash
uv run gdansk run build
uv run gdansk run dev --watch
```

| Flag | Purpose |
| --- | --- |
| `--watch` | Keep the task running until interrupted |
| `--host`, `--port` | Optional HTTP host/port for long-running tasks |

### `gdansk scripts`

List configured `[belgie.scripts]` entries.

```bash
uv run gdansk scripts
```

### `gdansk doctor`

Validate environment and project layout. Run this after bootstrap and when debugging setup issues.

```bash
uv run gdansk doctor
uv run gdansk doctor -F src/my_pkg/views
```

Checks:

- Python version (`>=3.12,<3.15`)
- `[belgie.dependencies]` table exists
- Frontend root contains `vite.config.ts` and `widgets/`
- belgie lockfile (`deno.lock`) at project root (warns if missing)
- `[belgie.scripts].build` and `.dev` entries (warns if missing)

Exit code 1 on failures; warnings do not fail the command.

## When to run what

| Situation | Command |
| --- | --- |
| New gdansk project | `gdansk init` → `gdansk install` → `gdansk doctor` |
| Changed `[belgie.dependencies]` | `gdansk install` |
| Validate setup before debugging | `gdansk doctor` |
| Build assets for production / CI | `gdansk build` |
| Test frontend in isolation | `gdansk dev` |
| List available frontend scripts | `gdansk scripts` |

## Quick reference

```bash
# Bootstrap
uv add gdansk
uv run gdansk init
uv run gdansk install
uv run gdansk doctor

# Development
uv run gdansk dev
uv run python -m <package>

# Production build
uv run gdansk build

# Dependency management
uv run gdansk lock
uv run gdansk update
uv run gdansk update "@gdansk/vite" --latest
```

For manual layout without `init`, see [quickstart.md](quickstart.md).

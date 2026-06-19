# CLI Reference

Invoke gdansk through `uv run gdansk` from the Python project root.

## Global flags

| Flag | Applies to | Purpose |
| --- | --- | --- |
| `-C`, `--project` | add, lock, update, build, dev, run, commands, doctor | Project root containing `[gdansk]` configuration |
| `-F`, `--frontend` | build, dev, doctor | Frontend root override |

Pass extra Vite or user-command arguments after `--`.

## Commands

### `gdansk init`

Scaffold `pyproject.toml`, `src/<package>/__main__.py`, the Vite config, and an example widget.

```bash
uv run gdansk init
uv run gdansk init --path ./my-server
uv run gdansk init --package my_mcp_server --force
uv run gdansk init --no-lock
```

Initialization writes `[gdansk.dependencies]`, locks dependencies by default, and never creates `package.json` or
`deno.json` in the frontend root.

### `gdansk add`

Add or replace a dependency and refresh `deno.lock`.

```bash
uv run gdansk add react "^19"
uv run gdansk add "@types/react" "^19" --dev
uv run gdansk add std_path "jsr:@std/path@^1"
```

Adding an existing alias moves it to the selected default or dev group.

### `gdansk lock`

Resolve all `[gdansk.dependencies]` and `[gdansk.dependencies.dev]` entries into the project-root `deno.lock`.

```bash
uv run gdansk lock
```

### `gdansk update`

Update all dependencies or selected aliases and write changes back to `pyproject.toml` and `deno.lock`.

```bash
uv run gdansk update
uv run gdansk update react vite --latest
```

### `gdansk build`

Run Vite's `build` command in the discovered frontend root.

```bash
uv run gdansk build
uv run gdansk build -F src/my_pkg/views
uv run gdansk build -- --emptyOutDir
```

### `gdansk dev`

Run the Vite development server until interrupted.

```bash
uv run gdansk dev
uv run gdansk dev --host 127.0.0.1 --port 14000
```

Prefer `ship.mcp(watch=True)` for integrated development.

### `gdansk run`

Run an array-based `[gdansk.commands]` entry from the project root.

```toml
[gdansk.commands]
lint = ["oxlint", "--fix"]
```

```bash
uv run gdansk run lint
uv run gdansk run lint -- --quiet
uv run gdansk run server --watch
```

Commands are package binaries, not shell strings; pipes, redirection, and shell expansion are unsupported.

### `gdansk commands`

List configured `[gdansk.commands]` entries.

### `gdansk doctor`

Validate Python compatibility, `[gdansk.dependencies]`, the frontend layout, and the project-root `deno.lock`.

## Recommended workflow

```bash
uv add gdansk
uv run gdansk init
uv run gdansk add <alias> <specifier>
uv run gdansk doctor
uv run gdansk dev
uv run gdansk build
```

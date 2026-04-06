# `gdansk-bundler`

`gdansk-bundler` exposes Rolldown to Python through a PyO3 extension module (`gdansk_bundler._core`). Types such as
`Bundler` and `BundlerOutput` are native extension classes, not Python duplicates of the Rust types.

## Usage

```python
from gdansk_bundler import Bundler

bundler = Bundler(
    input={"entry": "./index.ts"},
    cwd=".",
    resolve={"condition_names": ["import"]},
    output={"dir": "dist", "format": "esm"},
)

with bundler() as build:
    output = build()

print(output.chunks[0].file_name)
```

For async code, construct `AsyncBundlerContext` explicitly:

```python
from gdansk_bundler import AsyncBundlerContext, Bundler

bundler = Bundler(input="./index.ts", cwd=".")

async with AsyncBundlerContext(bundler) as build:
    output = await build({"format": "esm"}, write=False)
```

`input`, `cwd`, and path-like fields under `output` accept `str` or `os.PathLike` (including `pathlib.Path`). Relative
`cwd` values are resolved against the process current working directory.

## Supported First-Milestone Options

- `input`
- `cwd`
- `resolve.condition_names`
- `devtools`
- `output.dir`
- `output.file`
- `output.format`
- `output.entry_file_names`
- `output.chunk_file_names`
- `output.asset_file_names`
- `output.sourcemap`
- `output.name`

If a default `output` config is present, `build()` writes to disk by default. Pass `write=False` to generate output in
memory instead.

## Plugins

`Bundler(plugins=[...])` accepts a list of plugin mappings. Each plugin must include `name` (string) and may define
any of these optional callables (Rolldown hook names in `snake_case`). The `resolve_id` hook is registered with
`PinPost` ordering so it runs after Rolldown’s built-in resolvers (matching typical user-plugin expectations).

- `resolve_id(specifier: str, importer: str | None) -> None | str | dict` — return `None` to defer; a string sets the
  resolved module id; a dict must include `id` and may set `external` (`True` / `False` / `"absolute"` / `"relative"`),
  `normalize_external_id` (bool), or `package_json_path` (str).
- `load(id: str) -> None | dict` — return `None` to defer; otherwise a dict with required `code` (str) and optional
  `module_type` (str, Rolldown module type such as `js` or `css`).
- `transform(code: str, id: str, module_type: str) -> None | dict` — same argument order as Rolldown’s JS API;
  return `None` to defer; otherwise a dict with optional `code` and `module_type` to override the module.

Hooks run on a blocking worker thread with the GIL acquired; keep callbacks short and avoid awaiting from inside them.

Example combining `resolve_id` and `load` for a virtual module:

```python
VIRTUAL = "\0virtual:demo"

def resolve_id(spec: str, _importer: str | None) -> str | None:
    if spec == "virtual:demo":
        return VIRTUAL
    return None

def load(mid: str) -> dict | None:
    if mid == VIRTUAL:
        return {"code": "export const answer = 42;\n"}
    return None

Bundler(
    input="./entry.js",
    cwd=".",
    plugins=[{"name": "virtual-demo", "resolve_id": resolve_id, "load": load}],
    output={"format": "esm"},
)
```

## Current Limits

- Prefer `Bundler(external=...)` to mark bare specifiers as external; `resolve_id` may return a dict with `external`
  (`True` / `False` / `"absolute"` / `"relative"`) for other cases, consistent with Rolldown’s hook output shape.
- Plugin hooks do not yet receive Rolldown plugin contexts (`cwd`, `add_watch_file`, `resolve`, etc.); only the
  arguments above are passed.
- Watch mode is not supported yet.
- This package currently targets the one-shot `rolldown()` lifecycle rather than Rolldown's watcher or dev-mode APIs.

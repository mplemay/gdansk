# `gdansk-bundler`

`gdansk-bundler` is a Python-first wrapper around Rolldown for one-shot builds.

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

For async code:

```python
from gdansk_bundler import Bundler

bundler = Bundler(input="./index.ts", cwd=".")

async with bundler() as build:
    output = await build({"format": "esm"}, write=False)
```

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

## Current Limits

- Python plugins are not supported yet.
- Watch mode is not supported yet.
- This package currently targets the one-shot `rolldown()` lifecycle rather than Rolldown's watcher or dev-mode APIs.

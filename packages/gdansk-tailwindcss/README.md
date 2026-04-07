# gdansk-tailwindcss

Tailwind CSS v4-style transform for [`gdansk-bundler`](https://github.com/mplemay/gdansk) (Rolldown) using the embedded
[`gdansk-runtime`](https://github.com/mplemay/gdansk) JavaScript engine. Filesystem work (candidate scanning and
`@import` resolution) runs in Python; the runtime script only loads `tailwindcss`, calls `compile`, and
`build(candidates)`. No system Node binary is used.

## Requirements

- A `package.json` next to your front-end sources (typically your `views/` directory).
- The `tailwindcss` npm package installed under that root (`node_modules/tailwindcss`), matching the setup you would use
  with the in-repo Vite shim.

## Usage

```python
from pathlib import Path

from gdansk_bundler import Bundler
from gdansk_tailwindcss import TailwindCssPlugin

Bundler(
    # ...
    plugins=[TailwindCssPlugin(package_json=Path("views/package.json"))],
)
```

## Behavior and limits

- Python expands top-level CSS `@import` chains (relative paths and `node_modules` packages, including `exports` with a
  `style` entry where applicable) before invoking Tailwind. If Tailwind still calls `loadStylesheet`, the transform
  fails with an error—extend [`gdansk_tailwindcss._css_expand`](src/gdansk_tailwindcss/_css_expand.py) for new import
  shapes.
- Candidate utilities are collected with the same regex walk heuristic as the main `gdansk` `@tailwindcss/vite` shim.
- This is not a full port of upstream `@tailwindcss/vite` (no HMR, multi-plugin arrays, Oxide scanner parity, or
  Lightning CSS optimize pass). Native addons such as `@tailwindcss/oxide` may not load under the runtime; the
  regex-based scan remains the practical path.

## Development

Run this package’s tests from the repo root:

```bash
uv run pytest packages/gdansk-tailwindcss/src/gdansk_tailwindcss/__tests__/unit/
```

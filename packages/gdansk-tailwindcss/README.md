# gdansk-tailwindcss

Tailwind CSS v4-style transform for [`gdansk-bundler`](https://github.com/mplemay/gdansk) (Rolldown) using the embedded
[`gdansk-runtime`](https://github.com/mplemay/gdansk) JavaScript engine. It does not shell out to a system Node binary.

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

- Resolves and runs the project’s `tailwindcss` package, walks the project tree for utility candidates (same heuristic
  approach as the main `gdansk` `@tailwindcss/vite` shim), and runs `compile` / `build`.
- If that fails, it tries to load `@tailwindcss/vite` from `node_modules` and delegate to its transform hook (still
  constrained by the embedded runtime).
- This is not a full port of upstream `@tailwindcss/vite` (no HMR, multi-plugin arrays, Oxide scanner parity, or
  Lightning CSS optimize pass). Native addons such as `@tailwindcss/oxide` may not load under the runtime; the
  regex-based scan remains the practical path.

## Development

Run this package’s tests from the repo root:

```bash
uv run pytest packages/gdansk-tailwindcss/src/gdansk_tailwindcss/__tests__/unit/
```

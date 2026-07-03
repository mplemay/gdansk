# Adoption checklist

## Requirements

- Python `>=3.12,<3.15`
- Belgie `>=0.29.0`
- Vite `>=8.1,<9`
- React 19

Run `uv run gdansk init`, declare all frontend dependencies in `[gdansk.dependencies]`, then run
`uv run gdansk lock` and `uv run gdansk doctor`.

The frontend root contains `widgets/<name>/widget.tsx`. It does not contain app-level `package.json`, `deno.json`, or
`vite.config.ts` files.

```toml
[gdansk.dependencies]
vite = ">=8.1,<9"
"@gdansk/widget" = "^0.1.0"
react = "^19"
react-dom = "^19"
```

Each widget must default-export a function returning `render({...})`. Verify `uv run gdansk build` produces
`dist/gdansk-manifest.json` with complete HTML for every registered widget.

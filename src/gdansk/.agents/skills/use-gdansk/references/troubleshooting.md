# Troubleshooting

Start with `uv run gdansk doctor`, then check these boundaries in order:

| Symptom | Check |
| --- | --- |
| Frontend root missing | `Vite(...)` points at the directory containing `widgets/` |
| Widget not found | Decorator path is relative to `widgets/` and ends in `widget.tsx` or `widget.jsx` |
| Descriptor validation fails | Default export is a function returning `render({ widget: <Component /> })` |
| Plugin cannot resolve | Package is in `[gdansk.dependencies]`; run `uv run gdansk lock` |
| Plugin enters browser graph | Declare plugins inline in `render({ plugins: [...] })`; gdansk strips them from the client bundle |
| Port conflict | Choose a free base `Vite(..., port=...)`; widgets use consecutive ports |
| Production resource missing | Run `uv run gdansk build` and inspect `dist/gdansk-manifest.json` |
| CSS missing | Import CSS from the widget tree and confirm it is present inside the manifest HTML |
| Prebuilt startup fails | `watch=None` requires an existing manifest under `build_directory` |
| Belgie runtime panics | Verify Belgie `>=0.31.0` and reproduce with an Environment-backed Runtime |

Production manifest entries contain `{ entry, html }`; separate `inline.script`, `inline.styles`, or emitted asset files
indicate an obsolete build. There is no app-level Vite config to inspect.

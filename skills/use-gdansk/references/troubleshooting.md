# Troubleshooting

Use exact error text to choose the fastest fix.

## Error map

| Symptom or error text | Likely cause | Fix | Quick check |
| --- | --- | --- | --- |
| `must be a relative path` | Absolute path passed to `path=` | Pass a path relative to the views root | Inspect decorator input; remove absolute prefix |
| `must not contain traversal segments` | `.` or `..` in `path=` | Normalize to direct relative path | `rg -n "@ship\\.widget\\(" -n` and inspect `path=` |
| `must not start with widgets/` | `path` begins with `widgets/...` | Remove `widgets/` prefix in decorator argument | Change `Path("widgets/hello/widget.tsx")` to `Path("hello/widget.tsx")` |
| `must be a .tsx or .jsx file` | Wrong file name or extension | Rename to `widget.tsx` or `widget.jsx`; update `path=` | `find views/widgets -type f \| rg "widget\\.(tsx\|jsx)$"` |
| `was not found` / missing widget entry files | `path=` points at missing file | Create `widget.tsx` or `widget.jsx` in target widget directory | `find views/widgets/<name> -maxdepth 2 -type f` |
| `Client bundled output for ... not found. Has the bundler been run?` | Bundle did not run, failed, or output path is wrong | Start server with `ship.mcp(..., dev=True)` in development; confirm `views/vite.config.ts` imports `@gdansk/vite`; resolve upstream bundle errors | Check `views/dist/**/client.js` existence |
| `SSR bundled output for ... not found. Has the bundler been run?` | Effective SSR true but server bundle missing | Ensure SSR is enabled intentionally and bundle succeeded | Check `views/dist/**/server.js` existence |
| `Execution error: ...` during SSR | Server JS threw at runtime (SSR render or dependency issue) | Fix SSR widget default export and runtime-safe imports; retry | Open `server.js` bundle and run minimal SSR widget to isolate |
| Build fails with message containing `default` for widget | Widget component missing default export | Export default React component from `widget.tsx`/`widget.jsx` | `rg -n "export default" views/widgets/**/widget.tsx views/widgets/**/widget.jsx` |
| Tailwind or CSS missing in browser | Frontend build or import issue | Confirm CSS is imported from the widget tree and tooling in `views/` is configured | Check generated `dist/**/client.css` after dev startup |

## Structured diagnosis flow

1. Validate `path=` contract first.
2. Confirm `views/widgets/**/widget.tsx|jsx` exists and has default export.
3. Confirm `views/vite.config.ts` imports `@gdansk/vite` and the framework plugins you expect.
4. Confirm `views/package.json` has `type=module`, `react`, `react-dom`, and `@modelcontextprotocol/ext-apps`.
5. Confirm bundler outputs are present under `views/dist/`.
6. For SSR-specific failures, confirm `server.js` exists and isolate runtime errors.
7. For CSS-specific failures, confirm the `views` package PostCSS/Tailwind (or similar) setup.

## Minimal command set

```bash
# 1) list widget entrypoints
find views/widgets -type f | rg "widget\\.(tsx|jsx)$"

# 2) ensure default exports exist
rg -n "export default" views/widgets

# 3) check generated outputs
find views/dist -type f | sort
```

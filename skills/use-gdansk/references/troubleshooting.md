# Troubleshooting

Use exact error text to choose the fastest fix.

## Error map

| Symptom or error text | Likely cause | Fix | Quick check |
| --- | --- | --- | --- |
| `must be a relative path` | Absolute path passed to `widget=` | Pass a path relative to `views/widgets` | Inspect decorator input; remove absolute prefix |
| `must not contain traversal segments` | `.` or `..` in `widget=` | Normalize to direct relative path | `rg -n "@amber.tool\\(" -n` and inspect `widget=` |
| `must not start with widgets/` | `widget` begins with `widgets/...` | Remove `widgets/` prefix in decorator argument | Change `Path("widgets/hello/widget.tsx")` to `Path("hello/widget.tsx")` or `Path("hello")` |
| `must match **/widget.tsx or **/widget.jsx` | Wrong file name (for example `app.tsx`) or wrong shape | Rename to `widget.tsx` or `widget.jsx`; update decorator path | `find views/widgets -type f \| rg "widget\\.(tsx\|jsx)$"` |
| `was not found. Expected one of: .../widget.tsx, .../widget.jsx` | Directory shorthand points to missing widget entry files | Create `widget.tsx` or `widget.jsx` in target widget directory | `find views/widgets/<name> -maxdepth 2 -type f` |
| `Client bundled output for ... not found. Has the bundler been run?` | Bundle did not run, failed, or output path is wrong | Start app with `amber(dev=True)` or run production startup path; resolve upstream bundle errors | Check `views/.gdansk/**/client.js` existence |
| `SSR bundled output for ... not found. Has the bundler been run?` | Effective SSR true but server bundle missing | Ensure SSR is enabled intentionally and bundle succeeded | Check `views/.gdansk/**/server.js` existence |
| `Execution error: ...` during SSR | Server JS threw at runtime (SSR render or dependency issue) | Fix SSR widget default export and runtime-safe imports; retry | Open `server.js` bundle and run minimal SSR widget to isolate |
| Build fails with message containing `default` for widget | Widget component missing default export | Export default React component from `widget.tsx`/`widget.jsx` | `rg -n "export default" views/widgets/**/widget.tsx views/widgets/**/widget.jsx` |
| `Cannot find package '@tailwindcss/vite'` | `VitePlugin` references Tailwind but it is not installed in `views/node_modules` | Install `@tailwindcss/vite` and `tailwindcss` in the `views` package | `node --input-type=module -e \"import('@tailwindcss/vite').then(() => console.log('ok'))\"` |
| Tailwind transform not applied | Vite plugin not attached or no generated CSS to process | Add `plugins=[VitePlugin(specifier=\"@tailwindcss/vite\")]` and ensure `.gdansk/**/client.css` exists after bundle | Confirm `.gdansk/**/client.css` contains generated utilities such as `.mx-auto` |

## Structured diagnosis flow

1. Validate `widget=` contract first.
2. Confirm `views/widgets/**/widget.tsx|jsx` exists and has default export.
3. Confirm `views/package.json` has `type=module`, `react`, `react-dom`, and `@modelcontextprotocol/ext-apps`.
4. Confirm bundler outputs are present under `views/.gdansk/`.
5. For SSR-specific failures, confirm `server.js` exists and isolate runtime errors.
6. For CSS-specific failures, confirm the Vite plugin wiring and package availability.

## Minimal command set

```bash
# 1) list widget entrypoints
find views/widgets -type f | rg "widget\\.(tsx|jsx)$"

# 2) ensure default exports exist
rg -n "export default" views/widgets

# 3) check generated outputs
find views/.gdansk -type f | sort

# 4) check Tailwind Vite package availability
node --input-type=module -e "import('@tailwindcss/vite').then(() => console.log('tailwind vite ok'))"
```

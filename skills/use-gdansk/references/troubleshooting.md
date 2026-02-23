# Troubleshooting

Use exact error text to choose the fastest fix.

## Error map

| Symptom or error text | Likely cause | Fix | Quick check |
| --- | --- | --- | --- |
| `must be a relative path` | Absolute path passed to `page=` | Pass a path relative to `views/apps` | Inspect decorator input; remove absolute prefix |
| `must not contain traversal segments` | `.` or `..` in `page=` | Normalize to direct relative path | `rg -n "@amber.tool\\(" -n` and inspect `page=` |
| `must not start with apps/` | `page` begins with `apps/...` | Remove `apps/` prefix in decorator argument | Change `Path("apps/hello/page.tsx")` to `Path("hello/page.tsx")` or `Path("hello")` |
| `must match **/page.tsx or **/page.jsx` | Wrong file name (for example `app.tsx`) or wrong shape | Rename to `page.tsx` or `page.jsx`; update decorator path | `find views/apps -type f \| rg "page\\.(tsx\|jsx)$"` |
| `was not found. Expected one of: .../page.tsx, .../page.jsx` | Directory shorthand points to missing page entry files | Create `page.tsx` or `page.jsx` in target app directory | `find views/apps/<app> -maxdepth 2 -type f` |
| `Client bundled output for ... not found. Has the bundler been run?` | Bundle did not run, failed, or output path is wrong | Start app with `amber(dev=True)` or run production startup path; resolve upstream bundle errors | Check `views/.gdansk/**/client.js` existence |
| `SSR bundled output for ... not found. Has the bundler been run?` | Effective SSR true but server bundle missing | Ensure SSR is enabled intentionally and bundle succeeded | Check `views/.gdansk/**/server.js` existence |
| `Execution error: ...` during SSR | Server JS threw at runtime (SSR render or dependency issue) | Fix SSR page default export and runtime-safe imports; retry | Open `server.js` bundle and run minimal SSR page to isolate |
| Build fails with message containing `default` for app page | Page component missing default export | Export default React component from `page.tsx`/`page.jsx` | `rg -n "export default" views/apps/**/page.tsx views/apps/**/page.jsx` |
| `postcss-cli was not found in views/node_modules/.bin` | PostCSS plugin configured but CLI missing | Install `postcss` and `postcss-cli` in views package | `test -x views/node_modules/.bin/postcss && echo ok \|\| echo missing` |
| PostCSS transform not applied | Plugin not attached or no generated CSS to process | Add `plugins=[PostCSS()]` and ensure CSS exists in output | Confirm `.gdansk/**/client.css` exists after bundle |

## Structured diagnosis flow

1. Validate `page=` contract first.
2. Confirm `views/apps/**/page.tsx|jsx` exists and has default export.
3. Confirm `views/package.json` has `type=module`, `react`, `react-dom`, and `@modelcontextprotocol/ext-apps`.
4. Confirm bundler outputs are present under `views/.gdansk/`.
5. For SSR-specific failures, confirm `server.js` exists and isolate runtime errors.
6. For CSS-specific failures, confirm plugin wiring and PostCSS CLI availability.

## Minimal command set

```bash
# 1) list app entrypoints
find views/apps -type f | rg "page\\.(tsx|jsx)$"

# 2) ensure default exports exist
rg -n "export default" views/apps

# 3) check generated outputs
find views/.gdansk -type f | sort

# 4) check PostCSS CLI availability
test -x views/node_modules/.bin/postcss && echo "postcss ok" || echo "postcss missing"
```

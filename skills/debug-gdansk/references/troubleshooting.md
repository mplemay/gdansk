# Troubleshooting

Use exact error text to choose the fastest fix.

## Error map

| Symptom or error text | Likely cause | Fix | Quick check |
| --- | --- | --- | --- |
| `The views directory ... does not exist` | `Ship(..., views=...)` points at a missing directory | Point `views=` at the frontend package root that contains `package.json` and `widgets/` | Inspect the server entrypoint and confirm the resolved path |
| `The views directory ... is not a directory` | `views=` points at a file | Pass the package directory instead of a file path | Inspect the `Ship(...)` argument |
| `must be a relative path` | Absolute path passed to `path=` | Pass a path relative to the frontend package `widgets/` root | Inspect decorator input; remove the absolute prefix |
| `must not contain traversal segments` | `.` or `..` in `path=` | Normalize to a direct relative path | Inspect `@ship.widget(...)` and remove traversal |
| `must point to a widget.tsx or widget.jsx file` | Wrong file name or extension | Rename to `widget.tsx` or `widget.jsx`; update `path=` | List `widgets/**/widget.tsx` and `widget.jsx` files |
| `is not a file` for widget path | `path=` points at a missing widget entry file | Create `widget.tsx` or `widget.jsx` in the target widget directory | Confirm the file exists under `widgets/` |
| `has already been registered` for a widget | Same widget path registered twice | Remove the duplicate decorator or registration branch | Search for repeated registrations of the same path |
| `A tool with the name ... has already been registered` | Another tool on the same `MCPServer` already owns that name | Rename one of the tools or unify the registration site | Search for duplicated MCP tool names |
| `The frontend runtime did not start in time` | Vite did not boot, or Python and Vite disagree on host or port | Fix the Vite startup issue and keep `Ship(host, port)` and `gdansk({ host, port })` aligned | Check `vite.config.ts`, package dependencies, and the configured host/port on both sides |
| Backend or template edits do not trigger a browser reload | Full-reload watching is disabled | Enable `gdansk({ refresh: true })` or point `refresh` at explicit backend paths | Check `vite.config.ts` for the plugin `refresh` option |
| `Expected a production server entry at .../dist/server.js` | Production build did not complete | Run the app once in development first or fix upstream build failures | Confirm `dist/server.js` exists |
| `Failed to render widget ... invalid SSR payload` | SSR endpoint returned malformed JSON | Fix the SSR server implementation or the widget rendering path | Inspect the SSR response payload shape |
| `Execution error: ...` during SSR | Server-side render threw at runtime | Fix SSR-unsafe imports or rendering logic in the widget | Reduce the widget to a minimal default export and reintroduce imports incrementally |
| Widget loads but CSS is missing | CSS import or asset emission issue | Ensure styles are imported from the widget tree and that CSS is emitted into `dist/` | Check for `dist/**/client.css` and whether the widget imports its styles |

## Structured diagnosis flow

1. Validate the `Ship(..., views=...)` target first.
2. Validate `@ship.widget(path=...)` against the path contract.
3. Confirm the widget file exists and default-exports the component.
4. Confirm `vite.config.ts` imports `@gdansk/vite` and the framework plugins you expect.
5. If the repo customizes asset or widget directories, confirm `Ship(...)` and `gdansk(...)` use matching values.
6. Confirm the frontend package has the required dependencies.
7. Confirm bundle outputs exist under `dist/`.
8. For SSR failures, isolate runtime-safe imports and the default export first.
9. For CSS failures, confirm the stylesheet is imported somewhere in the widget tree.

## Minimal command set

```bash
# 1) list widget entrypoints
find frontend/widgets -type f | rg "widget\\.(tsx|jsx)$"

# 2) ensure default exports exist
rg -n "export default" frontend/widgets

# 3) check generated outputs
find frontend/dist -type f | sort
```

Replace `frontend/` and `frontend/widgets` with the actual frontend package and widgets directory when the repo uses
different paths.

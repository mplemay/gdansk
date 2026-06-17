# Troubleshooting

Use this file when gdansk is already present but something is broken. Diagnose from the failing boundary outward and
prefer exact error strings over speculative fixes.

## Identify the failing boundary first

Classify the issue before editing:

1. **Registration-time failure**
   - Invalid `Vite(...)` root path.
   - Invalid `@ship.widget(path=...)` input.
   - Duplicate widget or tool registration.
2. **Frontend startup or build failure**
   - Vite runtime never becomes healthy.
   - Production server bundle is missing.
   - Client bundle output is missing.
3. **Render or browser runtime failure**
   - Render request returns an execution error.
   - Rendered HTML is invalid or missing scripts.
   - CSS is not emitted or not loaded.

If the repo does not have gdansk wired yet, use [QUICKSTART.md](QUICKSTART.md) and [ADOPTION.md](ADOPTION.md) first.

## Validate the public contract

Before changing behavior:

- Confirm `Vite(...)` points at the frontend root.
- Confirm the frontend root contains `vite.config.ts` and `widgets/`.
- Confirm the widget file exists at `widgets/**/widget.tsx` or `widget.jsx`.
- Confirm `@ship.widget(path=...)` uses a path relative to `widgets/`.
- Confirm the widget default-exports the React component.
- Confirm the Python project's `pyproject.toml` declares `@gdansk/vite`, `vite`, `@vitejs/plugin-react`, `react`,
  `react-dom`, and `@modelcontextprotocol/ext-apps` in `[belgie.dependencies]`.

Use [PATH-CONTRACT.md](PATH-CONTRACT.md) for accepted and rejected widget path inputs.

## Match the failure to the smallest likely fix

- For validation errors, fix the path or duplicate registration directly.
- For build and startup failures, inspect `vite.config.ts`, belgie dependencies, and bundle outputs under `dist/`.
- For runtime host or port issues, keep `Vite(Path(...), host=..., port=...)` on `Ship(vite=...)` and
  `gdansk({ host, port })` aligned.
- For build output directory mismatches, keep `Vite(Path(...), build_directory=...)` and
  `gdansk({ buildDirectory })` aligned.
- For render errors, isolate the widget's default export and runtime-safe imports first.
- For CSS issues, confirm the styles are imported from the widget tree and emitted into the bundle.

## Error map

| Symptom or error text | Likely cause | Fix | Quick check |
| --- | --- | --- | --- |
| `The frontend root directory ... does not exist` | `Vite(...)` points at a missing directory | Point `Vite(...)` at the frontend root that contains `vite.config.ts` and `widgets/` | Inspect the server entrypoint and confirm the resolved path |
| `The frontend root directory ... is not a directory` | `Vite(...)` points at a file | Pass the frontend directory instead of a file path | Inspect the `Vite(...)` argument |
| `must be a relative path` | Absolute path passed to `path=` | Pass a path relative to the frontend `widgets/` root | Inspect decorator input; remove the absolute prefix |
| `must not contain traversal segments` | `.` or `..` in `path=` | Normalize to a direct relative path | Inspect `@ship.widget(...)` and remove traversal |
| `must point to a widget.tsx or widget.jsx file` | Wrong file name or extension | Rename to `widget.tsx` or `widget.jsx`; update `path=` | List `widgets/**/widget.tsx` and `widget.jsx` files |
| `is not a file` for widget path | `path=` points at a missing widget entry file | Create `widget.tsx` or `widget.jsx` in the target widget directory | Confirm the file exists under `widgets/` |
| `has already been registered` for a widget | Same widget path registered twice | Remove the duplicate decorator or registration branch | Search for repeated registrations of the same path |
| `A tool with the name ... has already been registered` | Another tool on the same `MCPServer` already owns that name | Rename one of the tools or unify the registration site | Search for duplicated MCP tool names |
| `The frontend dev server did not start in time` | Vite did not boot, or Python and Vite disagree on host or port | Fix the Vite startup issue and keep `Vite(Path(...), host=..., port=...)` and `gdansk({ host, port })` aligned | Check `vite.config.ts`, belgie dependencies, and the configured host/port on both sides |
| Backend or template edits do not trigger a browser reload | Full-reload watching is disabled | Enable `gdansk({ refresh: true })` or point `refresh` at explicit backend paths | Check `vite.config.ts` for the plugin `refresh` option |
| `The frontend build did not produce a manifest .../dist/gdansk-manifest.json` | Production build did not finish or stale output was reused | Rebuild the frontend and confirm `dist/gdansk-manifest.json` exists | Check `dist/` after a fresh build |
| `Execution error: ...` during render | HTML rendering threw at runtime | Fix render-unsafe imports or rendering logic in the widget | Reduce the widget to a minimal default export and reintroduce imports incrementally |
| Widget loads but CSS is missing | CSS import or asset emission issue | Ensure styles are imported from the widget tree and that CSS is emitted into `dist/` | Check for `dist/**/client.css` and whether the widget imports its styles |

## Structured diagnosis flow

1. Validate the `Vite(...)` frontend root target first.
2. Validate `@ship.widget(path=...)` against the path contract.
3. Confirm the widget file exists and default-exports the component.
4. Confirm `vite.config.ts` imports `@gdansk/vite` and the framework plugins you expect.
5. If the repo customizes the build output directory, confirm `Vite(..., build_directory=...)` and
   `gdansk({ buildDirectory })` match.
6. Confirm the Python project's `pyproject.toml` has the required `[belgie.dependencies]`.
7. Confirm bundle outputs exist under `dist/`.
8. For render failures, isolate runtime-safe imports and the default export first.
9. For CSS failures, confirm the stylesheet is imported somewhere in the widget tree.

## Verify after each fix

1. Restart the server in development if the runtime configuration changed.
2. Confirm the Vite dev client becomes reachable at `@vite/client`.
3. Confirm expected bundle outputs exist under `dist/`.
4. Fetch or open the widget resource and verify the rendered HTML references the expected assets.
5. Re-run the failing user flow instead of assuming the previous error was the only problem.

## Minimal command set

```bash
# 1) list widget entrypoints
find frontend/widgets -type f | rg "widget\\.(tsx|jsx)$"

# 2) ensure default exports exist
rg -n "export default" frontend/widgets

# 3) check generated outputs
find frontend/dist -type f | sort
```

Replace `frontend/` with the path to your frontend root; widget entry files always live under `<frontend>/widgets/`.

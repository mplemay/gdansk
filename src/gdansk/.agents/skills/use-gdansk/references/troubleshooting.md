# Troubleshooting

Use this file when gdansk is already present but something is broken. Diagnose from the failing boundary outward and
prefer exact error strings over speculative fixes.

## Step 0: run doctor

Before editing code, validate the project layout:

```bash
uv run gdansk doctor
```

This checks Python version, `[belgie.dependencies]`, frontend root, belgie lockfile (`deno.lock`), and `build`/`dev`
scripts. Fix any `fail` lines before proceeding. See [cli.md](cli.md) for what each check means.

## Identify the failing boundary first

Classify the issue before editing:

1. **Registration-time failure**
   - Invalid `Vite(...)` root path.
   - Invalid `@ship.widget(path=...)` input.
   - Duplicate widget or tool registration.
2. **Frontend startup or build failure**
   - Vite runtime never becomes healthy.
   - Production inline manifest is missing.
   - Manifest widget inline payload is missing.
3. **Render or browser runtime failure**
   - Render request returns an execution error.
   - Rendered HTML is invalid or missing scripts.
   - CSS is not imported into the inline widget payload.

If the repo does not have gdansk wired yet, use [quickstart.md](quickstart.md) and [adoption.md](adoption.md) first.

## Validate the public contract

Before changing behavior:

- Confirm `Vite(...)` points at the frontend root.
- Confirm the frontend root contains `vite.config.ts` and `widgets/`.
- Confirm the widget file exists at `widgets/**/widget.tsx` or `widget.jsx`.
- Confirm `@ship.widget(path=...)` uses a path relative to `widgets/`.
- Confirm the widget default-exports the React component.
- Confirm the Python project's `pyproject.toml` declares `@gdansk/vite`, `vite`, `@vitejs/plugin-react`, `react`,
  `react-dom`, and `@modelcontextprotocol/ext-apps` in `[belgie.dependencies]`.
- Confirm the belgie lockfile (`deno.lock`) exists at the Python project root (not under the frontend root).

Use [path-contract.md](path-contract.md) for accepted and rejected widget path inputs.
Use [rules/config-sync.md](../rules/config-sync.md) for host/port/buildDirectory alignment.

## Match the failure to the smallest likely fix

- For validation errors, fix the path or duplicate registration directly.
- For build and startup failures, inspect `vite.config.ts`, belgie dependencies, and `dist/gdansk-manifest.json`.
- For runtime host or port issues, keep `Vite(Path(...), host=..., port=...)` on `Ship(vite=...)` and
  `gdansk({ host, port })` aligned.
- For build output directory mismatches, keep `Vite(Path(...), build_directory=...)` and
  `gdansk({ buildDirectory })` aligned.
- For render errors, isolate the widget's default export and runtime-safe imports first.
- For CSS issues, confirm the styles are imported from the widget tree and present in the manifest's `inline.styles`.
- For missing deps, run `uv run gdansk install` instead of `npm install`.

## Error map

| Symptom or error text | Likely cause | Fix | Quick check |
| --- | --- | --- | --- |
| `doctor: N check(s) failed` | Project layout or deps invalid | Fix each `fail` line from `gdansk doctor` output | `uv run gdansk doctor` |
| `No [belgie.dependencies] table found` | Missing belgie tables | Run `gdansk init` or add tables manually | Inspect `pyproject.toml` |
| `belgie lockfile (deno.lock) missing at project root` | Lockfile not generated | Run `uv run gdansk install` | Check project root for `deno.lock` |
| `Legacy belgie lockfile (deno.lock) found under frontend` | Old lockfile location | Move `deno.lock` to Python project root | `find . -name deno.lock` |
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
| Widget loads but CSS is missing | CSS import or manifest extraction issue | Ensure styles are imported from the widget tree and present in `inline.styles` | Inspect `dist/gdansk-manifest.json` |
| Widget loads but tool call fails | Tool name mismatch | Align Python `name=` with `callServerTool({ name: ... })` | See [rules/widget-wiring.md](../rules/widget-wiring.md) |
| Assets 404 in production | Widget references Vite `public/` files or fetches network resources at runtime | Import assets through the widget graph or serve runtime resources separately | See [production.md](production.md) |

## Structured diagnosis flow

0. Run `uv run gdansk doctor` and fix failures.
1. Validate the `Vite(...)` frontend root target first.
2. Validate `@ship.widget(path=...)` against the path contract.
3. Confirm the widget file exists and default-exports the component.
4. Confirm `vite.config.ts` imports `@gdansk/vite` and the framework plugins you expect.
5. If the repo customizes the build output directory, confirm `Vite(..., build_directory=...)` and
   `gdansk({ buildDirectory })` match.
6. Confirm the Python project's `pyproject.toml` has the required `[belgie.dependencies]`.
7. Confirm `dist/gdansk-manifest.json` exists.
8. For render failures, isolate runtime-safe imports and the default export first.
9. For CSS failures, confirm the stylesheet is imported somewhere in the widget tree and appears in `inline.styles`.

## Verify after each fix

1. Run `uv run gdansk doctor` if layout or deps changed.
2. Restart the server in development if the runtime configuration changed.
3. Confirm the Vite dev client becomes reachable at `@vite/client`.
4. Confirm `dist/gdansk-manifest.json` exists.
5. Fetch or open the widget resource and verify the rendered HTML contains inline `<style>` and
   `<script type="module">`.
6. Re-run the failing user flow instead of assuming the previous error was the only problem.

## Minimal command set

```bash
# 0) validate project layout
uv run gdansk doctor

# 1) list widget entrypoints
find <frontend-root>/widgets -type f | rg "widget\\.(tsx|jsx)$"

# 2) ensure default exports exist
rg -n "export default" <frontend-root>/widgets

# 3) check generated output
find <frontend-root>/dist -type f | sort
```

Replace `<frontend-root>` with your frontend root path (`views/` from `gdansk init`, or `frontend/` in manual setups).

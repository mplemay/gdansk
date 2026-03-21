---
name: use-gdansk
description: Comprehensive gdansk implementation and debugging guide for MCP app UIs. Use when adding or fixing Amber and FastMCP tool UIs, wiring `@amber.tool(..., widget=...)` to React `views/widgets/**/widget.tsx` or `widget.jsx` entries, enabling SSR, configuring metadata or `cache_html`, adding a JS plugin adapter such as Tailwind CSS, mounting under FastAPI, or diagnosing gdansk bundling and runtime errors.
---

# Use Gdansk

Use this workflow for all gdansk work. Follow the steps in order and use the linked references for exact templates and
edge cases.

## 1) Classify the request

Map the request to one primary workflow before coding:

1. Add a new tool UI:
   - Register or update a Python tool.
   - Map it to a React widget with `@amber.tool(..., widget=...)`.
2. Fix a broken gdansk UI:
   - Resolve widget path validation errors.
   - Resolve missing bundle output or SSR runtime errors.
3. Add advanced integration:
   - Enable SSR globally or per tool.
   - Add metadata or disable cache.
   - Add JS plugin adapter handling.
   - Mount inside FastAPI.

If the user asks for multiple outcomes, implement one complete path first, then layer additional changes.

## 2) Validate project layout and dependencies first

Fail early on structure before writing feature code.

- Confirm the views root exists and contains `widgets/`.
- Confirm each UI entry point is `views/widgets/**/widget.tsx` or `views/widgets/**/widget.jsx`.
- Confirm each widget component has a default export.
- Confirm `views/package.json` has:
  - `"type": "module"`
  - `"@modelcontextprotocol/ext-apps"`
  - `"react"` and `"react-dom"`

Use [quickstart.md](references/quickstart.md) for the canonical baseline layout and minimum files.

## 3) Implement tool and widget wiring with strict path rules

Always treat `widget=` as a logical path under `views/widgets/`, never an absolute filesystem path. The directory
passed to `Amber(..., views=...)` can be named anything; `views` in docs is a conventional label for the npm package
root.

- Prefer directory shorthand (`widget=Path("hello")`) when the widget entry file is conventional.
- Use explicit file form only for disambiguation (`widget=Path("hello/widget.tsx")`).
- Never prefix the `widget` argument with `widgets/`.
- Never include `.` or `..` traversal segments.
- Keep the path relative.

Use [page-contract-and-tool-wiring.md](references/page-contract-and-tool-wiring.md) for accepted/rejected inputs and
`ui://` URI mapping behavior.

## 4) Apply optional integrations only when requested

Choose the smallest integration needed:

- SSR:
  - Global default: `Amber(..., ssr=True)`.
  - Per-tool override: `@amber.tool(..., ssr=True|False)`.
- HTML cache:
  - Default cached by fingerprint.
  - Disable via `Amber(..., cache_html=False)` when SSR output must be uncached per request.
- Metadata:
  - Set global metadata on `Amber`.
  - Override per tool with shallow top-level merge semantics.
- FastAPI:
  - Mount `mcp_app` and run its lifespan.
  - Use `streamable_http_path="/"` in `FastMCP` when mounted.
- Vite CSS plugins:
  - Add them through `plugins=[VitePlugin(...)]`.
  - Install plugin dependencies in the `views` package, such as `@tailwindcss/vite` and `tailwindcss`.

Use [integration-options.md](references/integration-options.md) for exact implementation shapes.

## 5) Verify and diagnose before finishing

After implementation:

1. Start server in dev mode and confirm bundle output appears under `views/.gdansk/`.
2. Open or fetch the UI resource and confirm rendered HTML includes client script.
3. For SSR paths, confirm server bundle exists and hydration path is correct.
4. For CSS changes, confirm generated CSS is present and transformed.

If anything fails, match the exact error string and follow [troubleshooting.md](references/troubleshooting.md).

## Guardrails

- Do not invent alternative widget conventions (for example `app.tsx`); gdansk expects `widget.tsx` or `widget.jsx`.
- Do not pass filesystem-absolute paths to `@amber.tool(widget=...)`.
- Do not use `widgets/...` as the decorator input prefix.
- Do not enable SSR without checking that the widget has a default export and that dependencies are SSR-compatible.
- Do not add a JS plugin adapter without installing its npm dependencies in the views package.

## Reference map

- Baseline templates and run commands: [quickstart.md](references/quickstart.md)
- Strict widget path contract and URI behavior:
  [page-contract-and-tool-wiring.md](references/page-contract-and-tool-wiring.md)
- SSR, metadata, FastAPI, JS plugin adapter options: [integration-options.md](references/integration-options.md)
- Error-driven diagnosis: [troubleshooting.md](references/troubleshooting.md)

---
name: use-gdansk
description: Comprehensive gdansk implementation and debugging guide for MCP app UIs. Use when adding or fixing Ship widget UIs, wiring `@ship.widget(..., path=...)` to React `views/widgets/**/widget.tsx` or `widget.jsx` entries, composing `ship.mcp(app=...)` with `mcp.server.MCPServer`, enabling SSR, configuring `Metadata`, registering extra tools with `@mcp.tool` on the same server, mounting under FastAPI, or diagnosing gdansk bundling and runtime errors.
---

# Use Gdansk

Use this workflow for all gdansk work. Follow the steps in order and use the linked references for exact templates and
edge cases.

## 1) Classify the request

Map the request to one primary workflow before coding:

1. Add a new tool UI:
   - Define a Python function and map it to a React widget with `@ship.widget(path=Path(".../widget.tsx"), name=...)`.
   - Use an `MCPServer` lifespan that enters `async with ship.mcp(app=app, dev=...)`.
2. Fix a broken gdansk UI:
   - Resolve widget path validation errors.
   - Resolve missing bundle output or SSR runtime errors.
3. Add advanced integration:
   - Enable SSR globally or per widget.
   - Add `Metadata` on `Ship` or per-widget where supported.
   - Register non-widget tools with `@mcp.tool` on the same `MCPServer`.
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

## 3) Implement widget wiring with strict path rules

Always treat `path=` in `@ship.widget` as a logical path under the views root (typically resolving to
`views/widgets/...`), never an absolute filesystem path. The directory passed to `Ship(..., views=...)` can be named
anything; `views` in docs is a conventional label for the package root (the directory that contains `package.json`).

- Use an explicit `.tsx` or `.jsx` file path (`path=Path("hello/widget.tsx")`).
- Never prefix the `path` argument with `widgets/`.
- Never include `.` or `..` traversal segments.
- Keep the path relative.

Use [page-contract-and-tool-wiring.md](references/page-contract-and-tool-wiring.md) for accepted/rejected inputs and
`ui://` URI mapping behavior.

## 4) Apply optional integrations only when requested

Choose the smallest integration needed:

- SSR:
  - Global default: `Ship(..., ssr=True)`.
  - Per-widget override: `@ship.widget(..., ssr=True|False)`.
- Metadata:
  - Set global metadata on `Ship` via `metadata=` (see `gdansk.metadata.Metadata`).
  - Per-widget metadata kwargs on `@ship.widget` where wired in `core.py`.
- Plain MCP tools (no React UI):
  - After `mcp = MCPServer(...)`, use `@mcp.tool(...)` or `mcp.add_tool(...)`.
- FastAPI:
  - Build `mcp_app = mcp.streamable_http_app(streamable_http_path="/")`, run its lifespan from FastAPI, mount at `/mcp`
    (or your chosen prefix).

Use [integration-options.md](references/integration-options.md) for exact implementation shapes.

## 5) Verify and diagnose before finishing

After implementation:

1. Start server with `ship.mcp(..., dev=True)` in development and confirm bundle output appears under `views/.gdansk/`.
2. Open or fetch the UI resource and confirm rendered HTML includes client script.
3. For SSR paths, confirm server bundle exists and hydration path is correct.
4. For CSS changes, confirm generated CSS is present.

If anything fails, match the exact error string and follow [troubleshooting.md](references/troubleshooting.md).

## Guardrails

- Do not invent alternative widget conventions (for example `app.tsx`); gdansk expects `widget.tsx` or `widget.jsx`.
- Do not pass filesystem-absolute paths to `@ship.widget(path=...)`.
- Do not use `widgets/...` as the `path` prefix.
- Do not enable SSR without checking that the widget has a default export and that dependencies are SSR-compatible.

## Reference map

- Baseline templates and run commands: [quickstart.md](references/quickstart.md)
- Strict widget path contract and URI behavior:
  [page-contract-and-tool-wiring.md](references/page-contract-and-tool-wiring.md)
- SSR, metadata, FastAPI, extra tools: [integration-options.md](references/integration-options.md)
- Error-driven diagnosis: [troubleshooting.md](references/troubleshooting.md)

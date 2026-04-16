---
name: use-gdansk
description: Adoption and implementation guide for using gdansk in any repository. Use when bootstrapping a new gdansk-backed MCP app, adding a `Ship` widget UI, wiring `ship.mcp(app=...)` with `MCPServer`, configuring the frontend package with `@gdansk/vite`, adding metadata or structured output, registering extra `@mcp.tool` tools on the same server, or mounting the MCP app inside FastAPI.
---

# Use Gdansk

Use this workflow when the job is to adopt gdansk in a repository or extend an existing gdansk integration with new
widgets or server capabilities. Keep the implementation on gdansk's public API surface. Do not send the user into
gdansk internals to figure out how to wire the feature.

## 1) Classify the request

Choose one primary path before making edits:

1. Bootstrap gdansk in a new repo:
   - Add the Python dependency.
   - Create the frontend package root and Vite config.
   - Add the first `@ship.widget(...)` tool and widget entry.
2. Add another widget to an existing repo:
   - Define the tool function.
   - Add a new `widgets/<name>/widget.tsx` or `widget.jsx`.
   - Register it with `@ship.widget(path=Path(".../widget.tsx"), name=...)`.
3. Add integration features:
   - Global or per-widget metadata.
   - `structured_output=True`.
   - Extra `@mcp.tool(...)` tools on the same `MCPServer`.
   - FastAPI mounting.

If the request is primarily about a broken existing integration, switch to `$debug-gdansk`.

## 2) Establish the repo layout and dependency baseline first

Fail early on missing package structure before writing feature code.

- Confirm the Python project installs `gdansk` and targets a supported Python version.
- Confirm the frontend package root exists and contains:
  - `package.json`
  - `vite.config.ts`
  - `widgets/`
- Confirm the frontend package is ESM with `"type": "module"`.
- Confirm `package.json` includes:
  - `@gdansk/vite`
  - `vite`
  - `@vitejs/plugin-react`
  - `react`
  - `react-dom`
  - `@modelcontextprotocol/ext-apps`
- After changing frontend dependencies, run `uv run deno install` from that package directory and update `deno.lock`
  when the repo tracks it.

Use [quickstart.md](references/quickstart.md) for the canonical baseline layout and minimum files.
Use [adoption-checklist.md](references/adoption-checklist.md) for compatibility and dependency expectations.

## 3) Wire the server and widget using only public APIs

Use the public integration points directly:

- Create `ship = Ship(views=Path(...))` with the frontend package root, not the widget directory.
- Register the UI tool with `@ship.widget(path=Path("hello/widget.tsx"), name="hello")`.
- Keep `path=` relative to `widgets/` inside the frontend package root.
- Use an `MCPServer` lifespan that enters `async with ship.mcp(app=app, watch=...)`.
- In the frontend package, import `@gdansk/vite` in `vite.config.ts` and compose it with the framework plugins you
  need.
- The Vite plugin now provides a default `@` alias to the frontend package root; only add a manual `@` alias when you
  need a different target.
- Prefer `gdansk({ refresh: true })` in real app repos so nearby Python or Jinja edits trigger a full browser reload.
- If you customize the runtime host or port, configure the same values in both `Ship(...)` and `gdansk(...)`.
- If you customize frontend directories, keep `Ship(assets=..., widgets_directory=...)` aligned with
  `gdansk({ buildDirectory: ..., widgetsDirectory: ... })`.
- Ensure the widget file default-exports the React component.

Do not use filesystem-absolute paths for widget registration. Do not assume the frontend package directory must be
named `views`; any directory passed to `Ship(..., views=...)` is valid.

## 4) Apply optional integrations only when requested

Choose the smallest integration needed:

- Metadata:
  - Set shared page metadata on `Ship(..., metadata=...)`.
  - Override per-widget metadata with `@ship.widget(..., metadata=...)`.
- Structured outputs:
  - Use `structured_output=True` on widget tools when the UI needs typed tool data instead of plain text parsing.
- Plain MCP tools (no React UI):
  - After `mcp = MCPServer(...)`, use `@mcp.tool(...)` or `mcp.add_tool(...)`.
- FastAPI:
  - Build `mcp_app = mcp.streamable_http_app(streamable_http_path="/")`, run its lifespan from FastAPI, mount it at
    `/mcp` (or your chosen prefix), and mount `ship.assets` at `/<assets_dir>` on the same public app.

Use [integration-options.md](references/integration-options.md) for exact implementation shapes.

## 5) Verify the integration before finishing

After implementation:

1. Start the server in development with `ship.mcp(..., watch=True)` (or `watch=False` to build on startup,
   `watch=None` when assets are prebuilt).
2. Confirm bundle output appears under `<frontend-package>/dist/`.
3. Open or fetch the UI resource and confirm the rendered HTML includes the client script.
4. Confirm the widget's `callServerTool(...)` calls use the registered MCP tool names.
5. For metadata work, confirm the expected title or meta tags appear in the rendered page.
6. For CSS changes, confirm the generated CSS file is present and referenced.

If startup, bundling, or rendering fails, switch to `$debug-gdansk`.

## Guardrails

- Do not tell the user to inspect gdansk internals for supported kwargs or wiring behavior when the public API already
  covers the task.
- Do not invent alternative widget entry conventions such as `app.tsx`; gdansk expects `widget.tsx` or `widget.jsx`.
- Do not use `widgets/...` as the `path` prefix in `@ship.widget(...)`.
- Ensure each widget default-exports the app component and that its imports are render-compatible.

## Reference map

- Baseline templates and run commands: [quickstart.md](references/quickstart.md)
- Compatibility and adoption checklist: [adoption-checklist.md](references/adoption-checklist.md)
- Metadata, structured output, FastAPI, extra tools: [integration-options.md](references/integration-options.md)

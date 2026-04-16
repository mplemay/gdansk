---
name: debug-gdansk
description: Debugging guide for broken gdansk integrations. Use when a gdansk widget fails to register, the frontend bundle or render runtime does not start, a `Ship` views path is wrong, widget output or CSS is missing, host and port configuration disagree, or an existing gdansk MCP app needs error-driven diagnosis.
---

# Debug Gdansk

Use this workflow when gdansk is already present but something is broken. Diagnose from the failing boundary outward and
prefer exact error strings over speculative fixes.

## 1) Identify the failing boundary first

Classify the issue before editing:

1. Registration-time failure:
   - Invalid `Ship(..., views=...)` path.
   - Invalid `@ship.widget(path=...)` input.
   - Duplicate widget or tool registration.
2. Frontend startup or build failure:
   - Vite runtime never becomes healthy.
   - Production server bundle is missing.
   - Client bundle output is missing.
3. Render or browser runtime failure:
   - Render request returns an execution error.
   - Rendered HTML is invalid or missing scripts.
   - CSS is not emitted or not loaded.

If the repo does not have gdansk wired yet and the task is mainly setup, switch to `$use-gdansk`.

## 2) Validate the public contract before changing behavior

Start with structure and contract checks:

- Confirm `Ship(..., views=...)` points at the frontend package root.
- Confirm the frontend package contains `package.json`, `vite.config.ts`, and `widgets/`.
- Confirm the widget file exists at `widgets/**/widget.tsx` or `widget.jsx`.
- Confirm `@ship.widget(path=...)` uses a path relative to `widgets/`.
- Confirm the widget default-exports the React component.
- Confirm the frontend package declares `@gdansk/vite`, `vite`, `@vitejs/plugin-react`, `react`, `react-dom`, and
  `@modelcontextprotocol/ext-apps`.

Use [path-contract.md](references/path-contract.md) for accepted and rejected widget path inputs.

## 3) Match the failure to the smallest likely fix

- For validation errors, fix the path or duplicate registration directly.
- For build and startup failures, inspect `vite.config.ts`, package dependencies, and bundle outputs under `dist/`.
- For runtime host or port issues, keep `Ship(host=..., port=...)` and `gdansk({ host, port })` aligned.
- For custom directory issues, keep `Ship(assets=..., widgets_directory=...)` and
  `gdansk({ buildDirectory, widgetsDirectory })` aligned.
- For render errors, isolate the widget's default export and runtime-safe imports first.
- For CSS issues, confirm the styles are imported from the widget tree and emitted into the bundle.

Use [troubleshooting.md](references/troubleshooting.md) for error-to-fix mapping.

## 4) Verify after each fix

After each change:

1. Restart the server in development if the runtime configuration changed.
2. Confirm the Vite dev client becomes reachable at `@vite/client`.
3. Confirm expected bundle outputs exist under `dist/`.
4. Fetch or open the widget resource and verify the rendered HTML references the expected assets.
5. Re-run the failing user flow instead of assuming the previous error was the only problem.

## Guardrails

- Do not rewrite the integration architecture when a path, dependency, or runtime mismatch explains the failure.
- Do not use absolute widget paths or `widgets/...` prefixes in `@ship.widget(...)`.
- Do not debug by guessing at internal gdansk behavior when the public contract or emitted error already explains the
  problem.

## Reference map

- Widget path contract and `ui://` mapping: [path-contract.md](references/path-contract.md)
- Error-driven diagnosis: [troubleshooting.md](references/troubleshooting.md)

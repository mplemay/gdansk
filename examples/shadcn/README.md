# shadcn example

This example shows a richer gdansk integration with:

- a widget tool registered with `structured_output=True`
- additional plain `@mcp.tool(...)` handlers on the same `MCPServer`
- a frontend package using `shadcn/ui` components and local styling

Use it when another repository already has the basic gdansk wiring and needs a more realistic multi-tool UI pattern.

## Run

```bash
uv sync
uv run main
```

If you change frontend dependencies under `src/shadcn/views/`, re-run:

```bash
cd src/shadcn/views
uv run deno install
```

For agent-driven setup, prefer `$use-gdansk`.

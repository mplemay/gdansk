# get-time example

This is the smallest copyable gdansk example in the repo. It demonstrates:

- one `Ship` instance pointed at a local frontend package
- one `@ship.widget(...)` tool
- a React widget calling the MCP tool through `@modelcontextprotocol/ext-apps`

Use this example as the baseline reference when another repository needs its first gdansk-backed widget.

## Run

```bash
uv sync
uv run main
```

If you change frontend dependencies under `src/get_time/views/`, re-run:

```bash
cd src/get_time/views
uv run deno install
```

For agent-driven setup, prefer `$use-gdansk`.

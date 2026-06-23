# get-time example

This is the smallest copyable gdansk example in the repo. It demonstrates:

- one `Ship` instance pointed at a local frontend root
- one `@ship.widget(...)` tool
- a React widget calling the MCP tool through `@modelcontextprotocol/ext-apps`

Use this example as the baseline reference when another repository needs its first gdansk-backed widget.

## Run

```bash
uv sync
uv run main
```

If you change frontend dependencies in `pyproject.toml`, re-run:

```bash
uv run gdansk lock
```

For agent-driven setup, prefer `$use-gdansk`.

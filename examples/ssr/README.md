# SSR example

## Run

```bash
uv sync
uv run main
```

This example demonstrates enabling server-side rendering globally with `Amber(ssr=True)`.
The tool UI is rendered on the server with `renderToString`, then hydrated client-side.

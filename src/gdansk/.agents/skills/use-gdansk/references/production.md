# Production

Use `uv run gdansk build` in CI and deploy the configured build directory with the Python service. At runtime, use
`ship.mcp(app=mcp, watch=None)` to consume the prebuilt `gdansk-manifest.json` without starting frontend tooling.

Every manifest widget contains `{ entry, html }`, where `html` is a complete self-contained document. Builds reject
extra chunks and non-inlined assets, so no static widget asset mount is required.

Use `watch=False` when startup should rebuild widgets. Use `watch=True` only for local development.

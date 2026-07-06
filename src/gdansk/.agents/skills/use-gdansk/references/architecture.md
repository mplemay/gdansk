# Architecture

`Ship` registers Python tools and MCP HTML resources. `Vite` locates the frontend root and asks Belgie to run the
`@gdansk/widget` Deno build/dev runtime.

Each `widgets/**/widget.{tsx,jsx}` module returns a branded descriptor containing a React element, HTML metadata,
server-only plugin references, and restricted Vite configuration.

Production uses Vite `createBuilder` independently per widget. The browser entry calls the module's default export,
validates the descriptor, and mounts only `definition.widget`. JavaScript, CSS, and imported assets are inlined into a
complete escaped HTML document stored at `widgets.<key>.html` in `gdansk-manifest.json`.

`ship.mcp(watch=True)` and `watch=False` both build widgets and serve that same self-contained HTML. With `watch=True`,
`watchfiles` rebuilds the manifest when frontend files change. MCP hosts re-serve widget HTML inside sandbox iframes, so
integrated development must not depend on external Vite dev asset URLs.

`uv run gdansk dev` starts one isolated Vite server per widget for optional standalone HMR outside the MCP host. A
temporary manifest maps widget keys to transformed page endpoints on ports beginning at `Vite(..., port=13714)`.

`watch=True` builds and watches for changes, `watch=False` builds on startup, and `watch=None` reads a prebuilt
manifest.

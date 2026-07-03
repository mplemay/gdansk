# Architecture

`Ship` registers Python tools and MCP HTML resources. `Vite` locates the frontend root and asks Belgie to run the
`@gdansk/widget` Deno build/dev runtime.

Each `widgets/**/widget.{tsx,jsx}` module returns a branded descriptor containing a React element, HTML metadata,
server-only plugin references, and restricted Vite configuration.

Production uses Vite `createBuilder` independently per widget. The browser entry calls the module's default export,
validates the descriptor, and mounts only `definition.widget`. JavaScript, CSS, and imported assets are inlined into a
complete escaped HTML document stored at `widgets.<key>.html` in `gdansk-manifest.json`.

Development runs one Vite server per widget in a single `gdansk-widget dev` process. A temporary manifest maps widget
keys to transformed page endpoints. This isolates plugin state while retaining Vite's module runner, HMR, and React
Refresh.

`watch=True` starts development servers, `watch=False` builds on startup, and `watch=None` reads a prebuilt manifest.

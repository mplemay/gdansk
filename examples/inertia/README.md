# Inertia example

This example shows the new Ship-backed Inertia flow for FastAPI: one HTML shell on the first request, JSON page
payloads on subsequent visits, session-backed validation errors, flash messages, and a convention-driven Vite page
build powered by `gdanskPages()`.

The frontend follows the `app/` contract:

- `app/page.tsx` is the root Inertia page and is rendered from Python with `page.render("/")`.
- `app/**/page.tsx` maps nested folders to slash-delimited component ids.
- `app/**/layout.tsx` wraps the page in the same folder and any parent folders.

## Run

```bash
uv sync
cd src/gdansk_inertia_example/views
uv run deno install
cd ../../..
uv run uvicorn main:app --reload
```

Open `http://127.0.0.1:8000`.

## Production mode

```bash
PRODUCTION=true uv run uvicorn main:app
```

Development runs `ship.inertia(...).lifespan(watch=True)` so the page loads from the Vite dev server. Production runs
the one-shot `vite build` path on startup and serves the emitted assets from `ship.assets`.

# Inertia example

This example shows the new Ship-backed Inertia flow for FastAPI: one HTML shell on the first request, JSON page
payloads on subsequent visits, session-backed validation errors, flash messages, and a standard Vite page build driven
by `gdanskPages()`.

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

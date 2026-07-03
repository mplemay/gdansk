# Configuration ownership

Python `Vite(...)` owns the frontend root, base development host/port, and production build directory. Each widget's
`render({...})` descriptor owns its supported Vite resolution, CSS, `define`, and optimization settings.

Do not create a global app-level Vite config. Gdansk reserves `root`, `configFile`, `server`, `build`, `builder`, and
`environments`, and rejects those keys in widget descriptors.

# Config Sync

Python `Vite(...)` and `@gdansk/vite` plugin options must stay aligned.

## Contents

- Host and port
- Build output directory
- Default values

---

## Host and port

Default frontend runtime address is `127.0.0.1:13714`. If you change it, update both sides.

**Incorrect:**

```python
ship = Ship(vite=Vite(frontend_path, host="127.0.0.1", port=14000))
```

```ts
export default defineConfig({
  plugins: [gdansk({ refresh: true }), react()],
});
```

**Correct:**

```python
ship = Ship(vite=Vite(frontend_path, host="127.0.0.1", port=14000))
```

```ts
export default defineConfig({
  plugins: [gdansk({ host: "127.0.0.1", port: 14000, refresh: true }), react()],
});
```

---

## Build output directory

Default is `dist`. Custom directories must match on both sides.

**Incorrect:**

```python
ship = Ship(vite=Vite(frontend_path, build_directory="public/ui"))
```

```ts
export default defineConfig({
  plugins: [gdansk({ refresh: true }), react()],
});
```

**Correct:**

```python
ship = Ship(vite=Vite(frontend_path, build_directory="public/ui"))
```

```ts
export default defineConfig({
  plugins: [gdansk({ buildDirectory: "public/ui", refresh: true }), react()],
});
```

---

## Default values

When using defaults, both sides can omit host/port/buildDirectory:

- Python: `Vite(frontend_path)` → `127.0.0.1:13714`, `dist`
- Vite: `gdansk({ refresh: true })` → same defaults

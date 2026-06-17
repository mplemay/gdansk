# Widget Wiring

Align Python tool registration, React widget code, and frontend dependencies.

## Contents

- Tool name alignment
- Default export
- Asset mounting
- belgie dependencies

---

## Tool name alignment

**Incorrect:**

```python
@ship.widget(path=Path("hello/widget.tsx"), name="greet")
def greet(name: str) -> list[TextContent]: ...
```

```tsx
await app.callServerTool({ name: "hello", arguments: { name } });
```

**Correct:**

```python
@ship.widget(path=Path("hello/widget.tsx"), name="greet")
def greet(name: str) -> list[TextContent]: ...
```

```tsx
await app.callServerTool({ name: "greet", arguments: { name } });
```

---

## Default export

**Incorrect:**

```tsx
export function App() {
  return <main>Hello</main>;
}
```

**Correct:**

```tsx
export default function App() {
  return <main>Hello</main>;
}
```

---

## Asset mounting

**Incorrect:**

```python
app = mcp.streamable_http_app()
uvicorn.run(app, port=3001)
```

**Correct:**

```python
app = mcp.streamable_http_app()
app.mount(path=ship.assets_path, app=ship.assets)
uvicorn.run(app, port=3001)
```

Production widgets load hydration assets from `ship.assets_path` (default `/dist`).

---

## belgie dependencies

**Incorrect:** adding `package.json` in the frontend root or running `npm install`.

**Correct:** declare deps in `pyproject.toml` and install from the Python project root:

```toml
[belgie.dependencies]
"@gdansk/vite" = "^0.1.0"
"@modelcontextprotocol/ext-apps" = "^1.5.0"
react = "^19"
vite = "8.0.8"
```

```bash
uv run gdansk install
```

Keep the belgie lockfile (`deno.lock`) at the Python project root.

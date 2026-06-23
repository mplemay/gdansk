# Widget Wiring

Align Python tool registration, React widget code, and frontend dependencies.

## Contents

- Tool name alignment
- Default export
- Production inline bundles
- gdansk dependencies

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

## Production inline bundles

**Incorrect:**

```text
Expected production files:
dist/hello/client.js
dist/hello/client.css
```

**Correct:**

```python
app = mcp.streamable_http_app()
uvicorn.run(app, port=3001)
```

Production widgets return inline JS/CSS inside the `ui://` HTML resource. The only production file gdansk needs is
`dist/gdansk-manifest.json`.

---

## gdansk dependencies

**Incorrect:** adding `package.json` in the frontend root or running `npm install`.

**Correct:** declare deps in `pyproject.toml` and lock them from the Python project root:

```toml
[gdansk.dependencies]
"@gdansk/vite" = "^0.1.0"
"@modelcontextprotocol/ext-apps" = "^1.5.0"
react = "^19"
vite = "8.0.14"
```

```bash
uv run gdansk lock
```

Keep the gdansk lockfile (`deno.lock`) at the Python project root.

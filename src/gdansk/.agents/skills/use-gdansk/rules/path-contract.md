# Widget Path Contract

See [references/path-contract.md](../references/path-contract.md) for the full contract table and URI derivation.

## Contents

- Frontend root vs widgets directory
- Relative path only
- Entry file naming
- No widgets/ prefix in decorator

---

## Frontend root vs widgets directory

**Incorrect:**

```python
ship = Ship(vite=Vite(Path(__file__).parent / "views" / "widgets"))
```

**Correct:**

```python
ship = Ship(vite=Vite(Path(__file__).parent / "views"))
```

`Vite(...)` receives the frontend root containing `widgets/`.

---

## Relative path only

**Incorrect:**

```python
@ship.widget(path=Path("/abs/path/hello/widget.tsx"), name="hello")
```

**Correct:**

```python
@ship.widget(path=Path("hello/widget.tsx"), name="hello")
```

---

## No widgets/ prefix in decorator

**Incorrect:**

```python
@ship.widget(path=Path("widgets/hello/widget.tsx"), name="hello")
```

**Correct:**

```python
@ship.widget(path=Path("hello/widget.tsx"), name="hello")
```

---

## Entry file naming

**Incorrect:**

```python
@ship.widget(path=Path("hello/app.tsx"), name="hello")
```

**Correct:**

```python
@ship.widget(path=Path("hello/widget.tsx"), name="hello")
```

Entry files must be named `widget.tsx` or `widget.jsx` under `widgets/<name>/`.

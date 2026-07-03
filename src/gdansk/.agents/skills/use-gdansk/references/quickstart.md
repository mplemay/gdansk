# Quick start

```text
src/example/
├── __main__.py
└── views/
    └── widgets/
        └── hello/
            └── widget.tsx
```

```python
from pathlib import Path

from gdansk import Ship, Vite

ship = Ship(vite=Vite(Path(__file__).parent / "views"))


@ship.widget(path=Path("hello/widget.tsx"), name="hello")
def hello() -> str:
    return "hello"
```

```tsx
import { render } from "@gdansk/widget";

function Hello() {
  return <main>Hello</main>;
}

export default function widget() {
  return render({ metadata: { title: "Hello" }, widget: <Hello /> });
}
```

```toml
[gdansk.dependencies]
vite = ">=8.1,<9"
"@gdansk/widget" = "^0.1.0"
react = "^19"
react-dom = "^19"
```

Run `uv run gdansk lock`, `uv run gdansk doctor`, then `uv run gdansk dev` or start the Python server with
`ship.mcp(app=..., watch=True)`.

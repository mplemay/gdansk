# Widget path contract and `@ship.widget` wiring

This file defines the strict `path` contract for `@ship.widget(...)`.

## Core rules

1. Pass a relative path only.
2. Do not include traversal segments (`.` or `..`).
3. Do not prefix with `widgets/` in decorator input.
4. The path must end with `.tsx` or `.jsx` (named `widget.tsx` or `widget.jsx` under a widget directory).
5. Ensure the target file exists under `views/widgets/` relative to the `Ship` views root.

## Contract table

| `path` input in `@ship.widget` | Accepted | Resolution behavior | Resource URI |
| --- | --- | --- | --- |
| `Path("hello/widget.tsx")` | Yes (if file exists under views) | explicit file | `ui://hello` |
| `Path("nested/page/widget.tsx")` | Yes | explicit file | `ui://nested/page` |
| `Path("hello/widget.jsx")` | Yes | explicit file | `ui://hello` |
| `"widgets/hello/widget.tsx"` | No | rejected: must not start with `widgets/` | n/a |
| `Path("hello")` | No | rejected: must be `.tsx` or `.jsx` | n/a |
| `Path("simple.tsx")` | No | rejected: must be `widget.tsx` or `widget.jsx` | n/a |
| `Path("/abs/path/widget.tsx")` | No | rejected: must be relative | n/a |
| `Path("hello/../hello/widget.tsx")` | No | rejected: traversal not allowed | n/a |

## How wiring works

Minimal pattern:

```python
from pathlib import Path
from mcp.types import TextContent

@ship.widget(path=Path("hello/widget.tsx"), name="hello")
def hello(name: str = "world") -> list[TextContent]:
    return [TextContent(type="text", text=f"Hello, {name}!")]
```

What gdansk registers:

1. The MCP tool (your function).
2. A UI resource with `uri="ui://hello"` and `mime_type="text/html;profile=mcp-app"`.
3. Tool metadata key: `meta["ui"]["resourceUri"] = "ui://hello"`.

## `ui://` URI derivation

Given `path` like `hello/widget.tsx` or `nested/page/widget.tsx`, URI is:

```text
ui://<parent_segments>
```

Examples:

- `hello/widget.tsx` -> `ui://hello`
- `nested/page/widget.tsx` -> `ui://nested/page`

## Output file mapping

For `hello/widget.tsx`:

- client bundle: `dist/hello/client.js`
- optional client css: `dist/hello/client.css`
- SSR server bundle (when enabled): `dist/hello/server.js`

## Guardrail checklist before merge

- The decorator `path` value is relative and does not start with `widgets/`.
- The target widget file exists and is named `widget.tsx` or `widget.jsx`.
- The React widget default exports the app component.
- The Python tool `name` and UI `callServerTool` names are aligned for expected UX.

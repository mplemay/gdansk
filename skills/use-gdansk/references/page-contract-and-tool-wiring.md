# Widget path contract and tool wiring

This file defines the strict `widget` contract for `@amber.tool(...)`.

## Core rules

1. Pass a relative path only.
2. Do not include traversal segments (`.` or `..`).
3. Do not prefix with `widgets/` in decorator input.
4. Accept only `**/widget.tsx` or `**/widget.jsx` entries.
5. For directory shorthand, prefer `widget.tsx`, then fall back to `widget.jsx`.
6. Ensure the target file exists under `views/widgets/`.

## Contract table

| `widget` input in decorator | Accepted | Resolution behavior | Resource URI |
| --- | --- | --- | --- |
| `Path("hello")` | Yes (if `views/widgets/hello/widget.tsx` or `widget.jsx` exists) | checks `hello/widget.tsx`, then `hello/widget.jsx` | `ui://hello` |
| `Path("nested/page")` | Yes | checks `nested/page/widget.tsx`, then `widget.jsx` | `ui://nested/page` |
| `Path("hello/widget.tsx")` | Yes | uses explicit file | `ui://hello` |
| `Path("hello/widget.jsx")` | Yes | uses explicit file | `ui://hello` |
| `"widgets/hello/widget.tsx"` | No | rejected: must not start with `widgets/` | n/a |
| `Path("simple.tsx")` | No | rejected: must match `**/widget.tsx` or `**/widget.jsx` | n/a |
| `Path("/abs/path/widget.tsx")` | No | rejected: must be relative | n/a |
| `Path("hello/../hello/widget.tsx")` | No | rejected: traversal not allowed | n/a |
| `Path("missing")` | No | file not found; expected `missing/widget.tsx` or `missing/widget.jsx` | n/a |

## How wiring works

Minimal pattern:

```python
from pathlib import Path
from mcp.types import TextContent

@amber.tool(name="hello", widget=Path("hello"))
def hello(name: str = "world") -> list[TextContent]:
    return [TextContent(type="text", text=f"Hello, {name}!")]
```

What gdansk registers:

1. The MCP tool (your function).
2. A UI resource with `uri="ui://hello"` and `mime_type="text/html;profile=mcp-app"`.
3. Tool metadata key: `meta["ui"]["resourceUri"] = "ui://hello"`.

## `ui://` URI derivation

Given `widget` resolved to `widgets/<segments>/widget.tsx|jsx`, URI is:

```text
ui://<segments>
```

Examples:

- `widgets/simple/widget.tsx` -> `ui://simple`
- `widgets/nested/page/widget.tsx` -> `ui://nested/page`

## Output file mapping

For `widgets/simple/widget.tsx`:

- client bundle: `.gdansk/simple/client.js`
- optional client css: `.gdansk/simple/client.css`
- SSR server bundle (when enabled): `.gdansk/simple/server.js`

## Guardrail checklist before merge

- The decorator `widget` value is relative and does not start with `widgets/`.
- The target widget file exists and is named `widget.tsx` or `widget.jsx`.
- The React widget default exports the app component.
- The Python tool and UI widget names are aligned for expected UX.

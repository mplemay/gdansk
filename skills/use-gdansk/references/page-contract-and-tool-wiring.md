# Page Contract and Tool Wiring

This file defines the strict `page` contract for `@amber.tool(...)`.

## Core rules

1. Pass a relative path only.
2. Do not include traversal segments (`.` or `..`).
3. Do not prefix with `apps/` in decorator input.
4. Accept only `**/page.tsx` or `**/page.jsx` entries.
5. For directory shorthand, prefer `page.tsx`, then fall back to `page.jsx`.
6. Ensure the target file exists under `views/apps/`.

## Contract table

| `page` input in decorator | Accepted | Resolution behavior | Resource URI |
| --- | --- | --- | --- |
| `Path("hello")` | Yes (if `views/apps/hello/page.tsx` or `page.jsx` exists) | checks `hello/page.tsx`, then `hello/page.jsx` | `ui://hello` |
| `Path("nested/page")` | Yes | checks `nested/page/page.tsx`, then `page.jsx` | `ui://nested/page` |
| `Path("hello/page.tsx")` | Yes | uses explicit file | `ui://hello` |
| `Path("hello/page.jsx")` | Yes | uses explicit file | `ui://hello` |
| `"apps/hello/page.tsx"` | No | rejected: must not start with `apps/` | n/a |
| `Path("simple.tsx")` | No | rejected: must match `**/page.tsx` or `**/page.jsx` | n/a |
| `Path("/abs/path/page.tsx")` | No | rejected: must be relative | n/a |
| `Path("hello/../hello/page.tsx")` | No | rejected: traversal not allowed | n/a |
| `Path("missing")` | No | file not found; expected `missing/page.tsx` or `missing/page.jsx` | n/a |

## How wiring works

Minimal pattern:

```python
from pathlib import Path
from mcp.types import TextContent

@amber.tool(name="hello", page=Path("hello"))
def hello(name: str = "world") -> list[TextContent]:
    return [TextContent(type="text", text=f"Hello, {name}!")]
```

What gdansk registers:

1. The MCP tool (your function).
2. A UI resource with `uri="ui://hello"` and `mime_type="text/html;profile=mcp-app"`.
3. Tool metadata key: `meta["ui"]["resourceUri"] = "ui://hello"`.

## `ui://` URI derivation

Given `page` resolved to `apps/<segments>/page.tsx|jsx`, URI is:

```text
ui://<segments>
```

Examples:

- `apps/simple/page.tsx` -> `ui://simple`
- `apps/nested/page/page.tsx` -> `ui://nested/page`

## Output file mapping

For `apps/simple/page.tsx`:

- client bundle: `.gdansk/simple/client.js`
- optional client css: `.gdansk/simple/client.css`
- SSR server bundle (when enabled): `.gdansk/simple/server.js`

## Guardrail checklist before merge

- The decorator `page` value is relative and does not start with `apps/`.
- The target page file exists and is named `page.tsx` or `page.jsx`.
- The React page default exports the app component.
- The Python tool and UI page names are aligned for expected UX.

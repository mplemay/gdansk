# React Widget Patterns

Use this file when building or extending React widgets with `@modelcontextprotocol/ext-apps`.

## `useApp` lifecycle

Every widget default-exports a React component that calls `useApp`:

```tsx
import { useApp } from "@modelcontextprotocol/ext-apps/react";

export default function App() {
  const { app, error } = useApp({
    appInfo: { name: "My Widget", version: "1.0.0" },
    capabilities: {},
    onAppCreated: (app) => {
      app.onerror = console.error;
    },
  });

  if (error) return <div>Error: {error.message}</div>;
  if (!app) return <div>Connecting...</div>;

  return <main>{/* widget UI */}</main>;
}
```

| Field | Purpose |
| --- | --- |
| `app` | MCP app instance; `null` while connecting |
| `error` | Connection error; render a fallback when set |
| `appInfo` | Widget identity passed to the MCP client |
| `capabilities` | MCP app capabilities object |
| `onAppCreated` | Callback when `app` is ready; use for `app.onerror` |

Gdansk mounts your default export into `#root` wrapped with `React.StrictMode`.

## Calling server tools

Tool `name` in Python must match `callServerTool({ name: ... })`:

```python
@ship.widget(path=Path("hello/widget.tsx"), name="hello")
def hello(name: str = "world") -> list[TextContent]:
    return [TextContent(type="text", text=f"Hello, {name}!")]
```

```tsx
const result = await app.callServerTool({
  name: "hello",
  arguments: { name: "from MCP UI" },
});
```

### Parsing text responses

```tsx
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";

const text = result.content?.find(
  (c): c is { type: "text"; text: string } => c.type === "text",
);
const value = text?.text ?? null;
```

### Stateful widget with tool call

```tsx
import { useApp } from "@modelcontextprotocol/ext-apps/react";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { useState } from "react";

export default function App() {
  const [toolResult, setToolResult] = useState<CallToolResult | null>(null);

  const { app, error } = useApp({
    appInfo: { name: "Get Time", version: "1.0.0" },
    capabilities: {},
    onAppCreated: (app) => {
      app.onerror = console.error;
    },
  });

  if (error) return <div>Error: {error.message}</div>;
  if (!app) return <div>Connecting...</div>;

  const serverTime = toolResult?.content?.find(
    (c): c is { type: "text"; text: string } => c.type === "text",
  )?.text;

  return (
    <main>
      <p>{serverTime ?? "No time fetched yet."}</p>
      <button
        onClick={async () => {
          const result = await app.callServerTool({ name: "get-time" });
          setToolResult(result);
        }}
      >
        Get Server Time
      </button>
    </main>
  );
}
```

## Structured output

When the Python tool uses `structured_output=True`, the UI receives typed data:

```python
@ship.widget(path=Path("todo/widget.tsx"), name="list-todos", structured_output=True)
def list_todos() -> list[Todo]:
    return todos
```

In the widget, read structured content from the tool result. The exact shape depends on how the MCP client
serializes structured output — inspect `result.content` or `result.structuredContent` at runtime:

```tsx
const result = await app.callServerTool({ name: "list-todos" });
const todos = result.structuredContent as Todo[] | undefined;
```

For multi-tool Python patterns (widget tools plus plain `@mcp.tool` handlers), see [integrations.md](integrations.md).

## ext-apps client APIs

Beyond `callServerTool`, widgets can interact with the MCP client host:

```tsx
// Send a message to the conversation
app.sendMessage({ role: "user", content: [{ type: "text", text: message }] });

// Send a log entry
app.sendLog({ level: "info", data: logMessage });

// Open a URL in the host
app.openLink({ url: link });
```

## Styling

Import styles from the widget tree — gdansk inlines imported CSS into the production widget HTML:

```tsx
import styles from "./global.css";

return <main className={styles.main}>...</main>;
```

For Tailwind, PostCSS, or component libraries (shadcn/ui), configure tooling in `vite.config.ts` and
declare dependencies in `[belgie.dependencies]`. Component libraries install like any other belgie dependency.
For multi-tool server setup, see [integrations.md](integrations.md).

## Widget metadata and CSP

Pass `meta=WidgetMeta(...)` to `@ship.widget` for UI visibility, CSP domains, and OpenAI-specific metadata:

```python
from gdansk import WidgetMeta

@ship.widget(
    path=Path("hello/widget.tsx"),
    name="hello",
    meta=WidgetMeta(ui={"visibility": ["model", "app"]}),
)
def hello() -> list[TextContent]: ...
```

For full decorator surface (`annotations`, `icons`, `metadata`), see [integrations.md](integrations.md).

## Common widget mistakes

- Tool `name` mismatch between Python and `callServerTool`
- Named export instead of `export default`
- Calling server tools before `app` is non-null
- Missing error/loading states for `useApp`
- Styles not imported anywhere in the widget tree (no `inline.styles` manifest payload)

For wiring rules, see [rules/widget-wiring.md](../rules/widget-wiring.md).

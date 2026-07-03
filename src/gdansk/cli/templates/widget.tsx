import { useApp } from "@modelcontextprotocol/ext-apps/react";
import { render } from "@gdansk/widget";

function App() {
  const { app, error } = useApp({
    appInfo: { name: "Hello", version: "1.0.0" },
    capabilities: {},
  });

  if (error) return <div>Error: {error.message}</div>;
  if (!app) return <div>Connecting...</div>;

  return (
    <main>
      <h2>Hello</h2>
      <button
        onClick={async () => {
          await app.callServerTool({
            name: "hello",
            arguments: { name: "from MCP UI" },
          });
        }}
      >
        Call hello
      </button>
    </main>
  );
}

export default function widget() {
  return render({ metadata: { title: "Hello" }, widget: <App /> });
}

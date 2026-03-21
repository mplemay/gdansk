import { useApp } from "@modelcontextprotocol/ext-apps/react";

export default function App() {
  const { app, error } = useApp({
    appInfo: { name: "Hello", version: "1.0.0" },
    capabilities: {},
  });

  if (error) return <div>Error: {error.message}</div>;
  if (!app) return <div>Connecting...</div>;

  return (
    <main>
      <h2>FastAPI Example</h2>
      <button
        onClick={async () => {
          await app.callServerTool({ name: "hello", arguments: { name: "from MCP UI" } });
        }}
      >
        Call hello
      </button>
    </main>
  );
}

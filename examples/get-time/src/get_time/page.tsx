import { useApp } from "@modelcontextprotocol/ext-apps/react";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import styles from "./global.css";

function GetTimeApp() {
  const [toolResult, setToolResult] = useState<CallToolResult | null>(null);
  const [message, setMessage] = useState("");
  const [logMessage, setLogMessage] = useState("");
  const [link, setLink] = useState("https://modelcontextprotocol.io");

  const { app, error } = useApp({
    appInfo: { name: "Get Time", version: "1.0.0" },
    capabilities: {},
    onAppCreated: (app) => {
      app.ontoolresult = async (result) => {
        setToolResult(result);
      };
      app.onerror = console.error;
    },
  });

  if (error) {
    return (
      <div className={styles.notice}>
        <strong>ERROR:</strong> {error.message}
      </div>
    );
  }
  if (!app) return <div className={styles.notice}>Connecting...</div>;

  const serverTime = (() => {
    const text = toolResult?.content?.find(
      (c): c is { type: "text"; text: string } => c.type === "text",
    );
    return text?.text ?? null;
  })();

  return (
    <main className={styles.main}>
      <h2>Get Time Example</h2>

      {/* Server Time */}
      <div className={styles.action}>
        <h3>Server Time</h3>
        <p>
          <span className={styles.serverTime}>
            {serverTime ?? "No time fetched yet."}
          </span>
        </p>
        <button onClick={() => app.callServerTool({ name: "get-time" })}>
          Get Server Time
        </button>
      </div>

      {/* Send Message */}
      <div className={styles.action}>
        <h3>Send Message</h3>
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Type a message..."
        />
        <button
          onClick={() => {
            if (message.trim()) app.sendMessage({ role: "user", content: [{ type: "text", text: message }] });
          }}
        >
          Send Message
        </button>
      </div>

      {/* Send Log */}
      <div className={styles.action}>
        <h3>Send Log</h3>
        <input
          value={logMessage}
          onChange={(e) => setLogMessage(e.target.value)}
          placeholder="Log message..."
        />
        <button
          onClick={() => {
            if (logMessage.trim()) app.sendLog({ level: "info", data: logMessage });
          }}
        >
          Send Log
        </button>
      </div>

      {/* Open Link */}
      <div className={styles.action}>
        <h3>Open Link</h3>
        <input
          value={link}
          onChange={(e) => setLink(e.target.value)}
          placeholder="https://..."
        />
        <button
          onClick={() => {
            if (link.trim()) app.openLink({ url: link });
          }}
        >
          Open Link
        </button>
      </div>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <GetTimeApp />
  </StrictMode>,
);

import { useApp } from "@modelcontextprotocol/ext-apps/react";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";

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
      <div style={{ padding: 20, color: "red" }}>
        <strong>ERROR:</strong> {error.message}
      </div>
    );
  }
  if (!app) return <div style={{ padding: 20 }}>Connecting...</div>;

  const serverTime = (() => {
    const text = toolResult?.content?.find(
      (c): c is { type: "text"; text: string } => c.type === "text",
    );
    return text?.text ?? null;
  })();

  const sectionStyle: React.CSSProperties = {
    marginBottom: 20,
    padding: 16,
    border: "1px solid #ddd",
    borderRadius: 8,
  };

  const buttonStyle: React.CSSProperties = {
    padding: "8px 16px",
    borderRadius: 4,
    border: "1px solid #ccc",
    cursor: "pointer",
    background: "#f5f5f5",
  };

  const inputStyle: React.CSSProperties = {
    padding: 8,
    borderRadius: 4,
    border: "1px solid #ccc",
    width: "100%",
    boxSizing: "border-box",
  };

  return (
    <main style={{ padding: 20, fontFamily: "system-ui, sans-serif", maxWidth: 500, margin: "0 auto" }}>
      <h2 style={{ marginTop: 0 }}>Get Time Example</h2>

      {/* Server Time */}
      <div style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>Server Time</h3>
        <p>{serverTime ?? "No time fetched yet."}</p>
        <button
          style={buttonStyle}
          onClick={() => app.callServerTool({ name: "get-time" })}
        >
          Get Server Time
        </button>
      </div>

      {/* Send Message */}
      <div style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>Send Message</h3>
        <textarea
          style={{ ...inputStyle, minHeight: 60, resize: "vertical" }}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Type a message..."
        />
        <button
          style={{ ...buttonStyle, marginTop: 8 }}
          onClick={() => {
            if (message.trim()) app.sendMessage({ role: "user", content: [{ type: "text", text: message }] });
          }}
        >
          Send Message
        </button>
      </div>

      {/* Send Log */}
      <div style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>Send Log</h3>
        <input
          style={inputStyle}
          value={logMessage}
          onChange={(e) => setLogMessage(e.target.value)}
          placeholder="Log message..."
        />
        <button
          style={{ ...buttonStyle, marginTop: 8 }}
          onClick={() => {
            if (logMessage.trim()) app.sendLog({ level: "info", data: logMessage });
          }}
        >
          Send Log
        </button>
      </div>

      {/* Open Link */}
      <div style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>Open Link</h3>
        <input
          style={inputStyle}
          value={link}
          onChange={(e) => setLink(e.target.value)}
          placeholder="https://..."
        />
        <button
          style={{ ...buttonStyle, marginTop: 8 }}
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

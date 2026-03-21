import { useApp } from "@modelcontextprotocol/ext-apps/react";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import styles from "../../global.css";

type Todo = {
  id: string;
  title: string;
  completed: boolean;
};

function getFirstTextContent(result: CallToolResult): string {
  const textPart = result.content.find((item) => item.type === "text");
  if (!textPart) {
    throw new Error("Tool response is missing text content.");
  }

  return textPart.text;
}

function parseTodos(result: CallToolResult): Todo[] {
  const payload = result.structuredContent;
  if (!payload || typeof payload !== "object") {
    throw new Error("Tool response is missing structured content.");
  }

  const parsedPayload = payload as { result?: unknown };
  if (!Array.isArray(parsedPayload.result)) {
    throw new Error("Tool response is missing a valid result array.");
  }

  return parsedPayload.result.map((todo, index) => {
    if (!todo || typeof todo !== "object") {
      throw new Error(`Todo at index ${index} is not an object.`);
    }

    const candidate = todo as Record<string, unknown>;
    if (
      typeof candidate.id !== "string" ||
      typeof candidate.title !== "string" ||
      typeof candidate.completed !== "boolean"
    ) {
      throw new Error(`Todo at index ${index} has an invalid shape.`);
    }

    return {
      id: candidate.id,
      title: candidate.title,
      completed: candidate.completed,
    };
  });
}

export default function App() {
  const [todos, setTodos] = useState<Todo[]>([]);
  const [newTitle, setNewTitle] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const { app, error } = useApp({
    appInfo: { name: "Todo List", version: "1.0.0" },
    capabilities: {},
    onAppCreated: (createdApp) => {
      createdApp.onerror = console.error;
    },
  });

  const syncTodos = useCallback(async (name: string, args?: Record<string, unknown>): Promise<boolean> => {
    if (!app) {
      return false;
    }

    setErrorMessage(null);
    setIsLoading(true);
    try {
      const result = await app.callServerTool({
        name,
        ...(args ? { arguments: args } : {}),
      });

      if (result.isError) {
        throw new Error(getFirstTextContent(result));
      }

      setTodos(parseTodos(result));
      return true;
    } catch (callError) {
      setErrorMessage(
        callError instanceof Error ? callError.message : "Unexpected error while syncing todos.",
      );
      return false;
    } finally {
      setIsLoading(false);
    }
  }, [app]);

  useEffect(() => {
    if (!app) return;
    void syncTodos("list-todos");
  }, [app, syncTodos]);

  if (error) {
    return (
      <div className={styles.notice}>
        <strong>ERROR:</strong> {error.message}
      </div>
    );
  }
  if (!app) return <div className={styles.notice}>Connecting...</div>;

  return (
    <main className={styles.main}>
      <Card className="mx-auto w-full max-w-xl">
        <CardHeader>
          <CardTitle>Todo List</CardTitle>
          <CardDescription>Manage todos stored in the MCP server process.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <form
            className="flex gap-2"
            onSubmit={async (event) => {
              event.preventDefault();
              if (isLoading) return;

              const trimmedTitle = newTitle.trim();
              if (!trimmedTitle) return;

              const wasSuccessful = await syncTodos("add-todo", { title: trimmedTitle });
              if (wasSuccessful) {
                setNewTitle("");
              }
            }}
          >
            <Input
              value={newTitle}
              onChange={(event) => setNewTitle(event.target.value)}
              placeholder="Add a todo"
              disabled={isLoading}
            />
            <Button type="submit" disabled={isLoading || newTitle.trim().length === 0}>
              Add
            </Button>
          </form>

          {errorMessage ? (
            <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {errorMessage}
            </div>
          ) : null}

          <ul className="space-y-2">
            {todos.length === 0 ? (
              <li className="rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground">
                No todos yet. Add one above.
              </li>
            ) : (
              todos.map((todo) => (
                <li key={todo.id} className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2">
                  <label className="flex min-w-0 items-center gap-3">
                    <Checkbox
                      checked={todo.completed}
                      disabled={isLoading}
                      onCheckedChange={() => {
                        void syncTodos("toggle-todo", { todo_id: todo.id });
                      }}
                      aria-label={`Toggle ${todo.title}`}
                    />
                    <span
                      className={`truncate text-sm ${todo.completed ? "text-muted-foreground line-through" : ""}`}
                    >
                      {todo.title}
                    </span>
                  </label>

                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={isLoading}
                    onClick={() => {
                      void syncTodos("delete-todo", { todo_id: todo.id });
                    }}
                  >
                    Delete
                  </Button>
                </li>
              ))
            )}
          </ul>
        </CardContent>
      </Card>
    </main>
  );
}

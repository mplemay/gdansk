"""Shadcn todo example server."""

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.middleware.cors import CORSMiddleware

from gdansk import Amber
from gdansk.experimental.postcss import PostCSS

mcp = FastMCP("Todo Server")
amber = Amber(mcp=mcp, views=Path(__file__).parent / "views", plugins=[PostCSS()])


@dataclass(slots=True, kw_only=True)
class Todo:
    """Todo item returned by the MCP tools."""

    id: str
    title: str
    completed: bool = False


TODOS: list[Todo] = []


def _serialize_todos() -> list[Todo]:
    return list(TODOS)


def _get_todo(todo_id: str) -> Todo:
    for todo in TODOS:
        if todo.id == todo_id:
            return todo

    msg = f"Todo {todo_id!r} not found."
    raise ValueError(msg)


@amber.tool(name="list-todos", page=Path("todo"), structured_output=True)
def list_todos() -> list[Todo]:
    """Return all todos."""
    return _serialize_todos()


@mcp.tool(name="add-todo", structured_output=True)
def add_todo(title: str) -> list[Todo]:
    """Add a todo and return the updated list."""
    cleaned_title = title.strip()
    if not cleaned_title:
        msg = "Title cannot be empty."
        raise ValueError(msg)

    TODOS.append(Todo(id=uuid4().hex, title=cleaned_title))
    return _serialize_todos()


@mcp.tool(name="toggle-todo", structured_output=True)
def toggle_todo(todo_id: str) -> list[Todo]:
    """Toggle the completion state for a todo."""
    todo = _get_todo(todo_id)
    todo.completed = not todo.completed
    return _serialize_todos()


@mcp.tool(name="delete-todo", structured_output=True)
def delete_todo(todo_id: str) -> list[Todo]:
    """Delete a todo and return the updated list."""
    todo = _get_todo(todo_id)
    TODOS.remove(todo)
    return _serialize_todos()


def main() -> None:
    """Run the development server for the todo example."""
    app = amber(dev=True)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    uvicorn.run(app, port=3001)


if __name__ == "__main__":
    main()

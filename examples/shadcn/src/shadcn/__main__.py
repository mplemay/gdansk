import json
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
from starlette.middleware.cors import CORSMiddleware

from gdansk import Amber
from gdansk.experimental.postcss import PostCSS

mcp = FastMCP("Todo Server")
amber = Amber(mcp=mcp, views=Path(__file__).parent / "views", plugins=[PostCSS()])


@dataclass(slots=True, kw_only=True)
class Todo:
    id: str
    title: str
    completed: bool = False


TODOS: list[Todo] = []


def _serialize_todos() -> list[TextContent]:
    payload = {"todos": [asdict(todo) for todo in TODOS]}
    return [TextContent(type="text", text=json.dumps(payload))]


def _get_todo(todo_id: str) -> Todo:
    for todo in TODOS:
        if todo.id == todo_id:
            return todo

    msg = f"Todo {todo_id!r} not found."
    raise ValueError(msg)


@amber.tool(name="list-todos", ui=Path("todo/app.tsx"))
def list_todos() -> list[TextContent]:
    return _serialize_todos()


@mcp.tool(name="add-todo")
def add_todo(title: str) -> list[TextContent]:
    cleaned_title = title.strip()
    if not cleaned_title:
        msg = "Title cannot be empty."
        raise ValueError(msg)

    TODOS.append(Todo(id=uuid4().hex, title=cleaned_title))
    return _serialize_todos()


@mcp.tool(name="toggle-todo")
def toggle_todo(todo_id: str) -> list[TextContent]:
    todo = _get_todo(todo_id)
    todo.completed = not todo.completed
    return _serialize_todos()


@mcp.tool(name="delete-todo")
def delete_todo(todo_id: str) -> list[TextContent]:
    todo = _get_todo(todo_id)
    TODOS.remove(todo)
    return _serialize_todos()


def main() -> None:
    app = mcp.streamable_http_app()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    with amber(dev=True):
        uvicorn.run(app, port=3001)


if __name__ == "__main__":
    main()

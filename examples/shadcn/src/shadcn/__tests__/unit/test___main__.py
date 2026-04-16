import sys
from pathlib import Path
from typing import Any, cast

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import shadcn.__main__ as todo_main

from gdansk.context import ShipContext
from gdansk.vite import Vite


@pytest.fixture(autouse=True)
def reset_todos():
    todo_main.TODOS.clear()
    yield
    todo_main.TODOS.clear()


def _structured_from_call_result(result: object) -> dict[str, Any]:
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[1], dict)
    return cast("dict[str, Any]", result[1])


def test_list_todos_returns_empty_list_initially():
    assert todo_main.list_todos() == []


def test_add_todo_adds_item():
    todos = todo_main.add_todo("Buy milk")
    assert len(todos) == 1
    assert todos[0].title == "Buy milk"
    assert todos[0].completed is False
    assert isinstance(todos[0].id, str)
    assert todos[0].id


def test_add_todo_rejects_empty_title():
    with pytest.raises(ValueError, match=r"Title cannot be empty\."):
        todo_main.add_todo("   ")


def test_toggle_todo_flips_completed_state():
    todo_main.add_todo("Buy milk")
    todo_id = todo_main.list_todos()[0].id
    todos = todo_main.toggle_todo(todo_id)
    assert todos[0].completed is True


def test_toggle_todo_errors_when_todo_not_found():
    with pytest.raises(ValueError, match="not found"):
        todo_main.toggle_todo("missing")


def test_delete_todo_removes_item():
    todo_main.add_todo("Buy milk")
    todo_id = todo_main.list_todos()[0].id
    assert todo_main.delete_todo(todo_id) == []


def test_delete_todo_errors_when_todo_not_found():
    with pytest.raises(ValueError, match="not found"):
        todo_main.delete_todo("missing")


async def test_mcp_list_tools_schemas_and_structured_calls(monkeypatch: pytest.MonkeyPatch):
    class NoopCM:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_args: object) -> None:
            return None

    vite_call_orig = Vite.__call__
    ctx_call_orig = ShipContext.__call__

    def vite_call(self: Vite, *, watch: bool | None) -> object:
        if self is todo_main.ship._vite:
            assert watch is True
            return NoopCM()
        return vite_call_orig(self, watch=watch)

    def ctx_call(self: ShipContext, *, watch: bool | None) -> object:
        if self is todo_main.ship._context:
            assert watch is True
            return NoopCM()
        return ctx_call_orig(self, watch=watch)

    monkeypatch.setattr(Vite, "__call__", vite_call)
    monkeypatch.setattr(ShipContext, "__call__", ctx_call)

    async with todo_main.ship.mcp(app=todo_main.mcp, watch=True):
        tools = await todo_main.mcp.list_tools()
        schemas = {tool.name: getattr(tool, "output_schema", getattr(tool, "outputSchema", None)) for tool in tools}

        for tool_name in ("list-todos", "add-todo", "toggle-todo", "delete-todo"):
            schema = schemas[tool_name]
            assert schema is not None
            assert schema["type"] == "object"
            assert "result" in schema["properties"]

        structured = _structured_from_call_result(await todo_main.mcp.call_tool("list-todos", {}))
        assert structured == {"result": []}

        structured = _structured_from_call_result(await todo_main.mcp.call_tool("add-todo", {"title": "Buy milk"}))
        assert len(structured["result"]) == 1
        assert structured["result"][0]["title"] == "Buy milk"
        assert structured["result"][0]["completed"] is False

        todo_id = structured["result"][0]["id"]
        structured = _structured_from_call_result(await todo_main.mcp.call_tool("toggle-todo", {"todo_id": todo_id}))
        assert structured["result"][0]["completed"] is True

        structured = _structured_from_call_result(await todo_main.mcp.call_tool("delete-todo", {"todo_id": todo_id}))
        assert structured == {"result": []}

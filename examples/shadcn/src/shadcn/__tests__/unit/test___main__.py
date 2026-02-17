import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import shadcn.__main__ as todo_main


@pytest.fixture(autouse=True)
def reset_todos():
    todo_main.TODOS.clear()
    yield
    todo_main.TODOS.clear()


def _todos_from_response(response):
    assert len(response) == 1
    assert response[0].type == "text"
    payload = json.loads(response[0].text)
    return payload["todos"]


def test_list_todos_returns_empty_list_initially():
    assert _todos_from_response(todo_main.list_todos()) == []


def test_add_todo_adds_item():
    todos = _todos_from_response(todo_main.add_todo("Buy milk"))
    assert len(todos) == 1
    assert todos[0]["title"] == "Buy milk"
    assert todos[0]["completed"] is False
    assert isinstance(todos[0]["id"], str)
    assert todos[0]["id"]


def test_add_todo_rejects_empty_title():
    with pytest.raises(ValueError, match="Title cannot be empty."):
        todo_main.add_todo("   ")


def test_toggle_todo_flips_completed_state():
    todo_main.add_todo("Buy milk")
    todo_id = _todos_from_response(todo_main.list_todos())[0]["id"]
    todos = _todos_from_response(todo_main.toggle_todo(todo_id))
    assert todos[0]["completed"] is True


def test_toggle_todo_errors_when_todo_not_found():
    with pytest.raises(ValueError, match="not found"):
        todo_main.toggle_todo("missing")


def test_delete_todo_removes_item():
    todo_main.add_todo("Buy milk")
    todo_id = _todos_from_response(todo_main.list_todos())[0]["id"]
    assert _todos_from_response(todo_main.delete_todo(todo_id)) == []


def test_delete_todo_errors_when_todo_not_found():
    with pytest.raises(ValueError, match="not found"):
        todo_main.delete_todo("missing")

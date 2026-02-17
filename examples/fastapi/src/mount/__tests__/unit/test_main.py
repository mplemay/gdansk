import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

pytest.importorskip("fastapi")

import main as fastapi_main


def _structured_from_call_result(result: object) -> dict[str, object]:
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[1], dict)
    return result[1]


def test_hello_returns_default_text():
    content = fastapi_main.hello()
    assert len(content) == 1
    assert content[0].type == "text"
    assert content[0].text == "Hello, world!"


@pytest.mark.asyncio
async def test_mcp_call_tool_returns_structured_hello():
    structured = _structured_from_call_result(await fastapi_main.mcp.call_tool("hello", {}))
    assert structured["result"][0]["text"] == "Hello, world!"


@pytest.fixture(scope="module")
def test_client():
    with TestClient(fastapi_main.app, base_url="http://127.0.0.1:8000") as client:
        yield client


def test_mcp_mount_redirects_to_trailing_slash(test_client):
    response = test_client.get("/mcp", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"].endswith("/mcp/")


def test_mcp_mount_endpoint_is_active(test_client):
    response = test_client.get("/mcp/", follow_redirects=False)
    assert response.status_code == 406


def test_mcp_does_not_have_double_prefix(test_client):
    response = test_client.get("/mcp/mcp", follow_redirects=False)
    assert response.status_code == 404

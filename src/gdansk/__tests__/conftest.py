from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from starlette.applications import Starlette

from gdansk.core import Amber


@pytest.fixture
def fixture_pages_path():
    return Path(__file__).parent / "fixtures" / "pages"


@pytest.fixture
def mock_mcp():
    mcp = MagicMock()
    app = Starlette()

    tool_calls = []
    resource_calls = []

    def _tool_decorator(**kwargs: object):
        tool_calls.append(kwargs)

        def _inner(fn):
            return fn

        return _inner

    def _resource_decorator(**kwargs: object):
        resource_calls.append(kwargs)

        def _inner(fn):
            resource_calls[-1]["handler"] = fn
            return fn

        return _inner

    mcp.tool = MagicMock(side_effect=_tool_decorator)
    mcp.resource = MagicMock(side_effect=_resource_decorator)
    mcp.streamable_http_app = MagicMock(return_value=app)
    mcp._tool_calls = tool_calls
    mcp._resource_calls = resource_calls

    return mcp


@pytest.fixture
def pages_dir(tmp_path, fixture_pages_path):
    dest = tmp_path / "pages"
    shutil.copytree(fixture_pages_path, dest)
    return dest


@pytest.fixture
def amber(mock_mcp, pages_dir):
    return Amber(mcp=mock_mcp, pages=pages_dir)

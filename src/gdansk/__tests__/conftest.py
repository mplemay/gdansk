from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gdansk.core import Amber


@pytest.fixture
def fixture_views_path():
    return Path(__file__).parent / "fixtures" / "views"


@pytest.fixture
def mock_mcp():
    mcp = MagicMock()

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
    mcp._tool_calls = tool_calls
    mcp._resource_calls = resource_calls

    return mcp


@pytest.fixture
def views_dir(tmp_path, fixture_views_path):
    dest = tmp_path / "views"
    shutil.copytree(fixture_views_path, dest)
    return dest


@pytest.fixture
def amber(mock_mcp, views_dir):
    return Amber(mcp=mock_mcp, views=views_dir)

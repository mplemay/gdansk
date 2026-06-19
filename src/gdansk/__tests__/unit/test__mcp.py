import importlib
import warnings
from importlib.metadata import version

import pytest

import gdansk._mcp as mcp_mod
from gdansk._mcp import FunctionResource, MCPServer, Tool


def test_mcp_compat_exports() -> None:
    app = MCPServer(name="test")
    assert app is not None
    assert FunctionResource is not None
    assert Tool is not None


def test_mcp_compat_uses_mcpserver_on_v2() -> None:
    if not version("mcp").startswith("2."):
        pytest.skip("only applies when mcp 2.x is installed")

    assert "mcpserver" in MCPServer.__module__


def test_mcp_compat_uses_fastmcp_on_v1() -> None:
    if not version("mcp").startswith("1."):
        pytest.skip("only applies when mcp 1.x is installed")

    assert "fastmcp" in MCPServer.__module__


def test_mcp_compat_deprecation_on_v1() -> None:
    if not version("mcp").startswith("1."):
        pytest.skip("only applies when mcp 1.x is installed")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        importlib.reload(mcp_mod)

    assert any("FastMCP" in str(w.message) for w in caught)

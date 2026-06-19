from importlib import import_module
from importlib.metadata import version
from typing import TYPE_CHECKING
from warnings import warn

from packaging.version import Version

MCP_V2_MAJOR: int = 2

if TYPE_CHECKING:
    from mcp.server.mcpserver.resources import FunctionResource
    from mcp.server.mcpserver.server import MCPServer
    from mcp.server.mcpserver.tools.base import Tool
elif Version(version("mcp")).major < MCP_V2_MAJOR:
    warn(
        "gdansk's FastMCP (mcp<2) compatibility is deprecated and will be removed "
        "once mcp 2.0 leaves pre-release. Upgrade to mcp>=2.0.",
        DeprecationWarning,
        stacklevel=2,
    )
    MCPServer = import_module("mcp.server.fastmcp").FastMCP
    FunctionResource = import_module("mcp.server.fastmcp.resources").FunctionResource
    Tool = import_module("mcp.server.fastmcp.tools.base").Tool
else:
    MCPServer = import_module("mcp.server").MCPServer
    FunctionResource = import_module("mcp.server.mcpserver.resources").FunctionResource
    Tool = import_module("mcp.server.mcpserver.tools.base").Tool

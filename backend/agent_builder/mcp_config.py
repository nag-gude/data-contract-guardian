"""Shared Fivetran MCP + ADK MCPToolset configuration.

Single place that constructs the ADK ``McpToolset`` pointing at the real
``fivetran/fivetran-mcp`` server over stdio (filtered to the three investigation tools), and a
small probe for whether the ``google-adk`` SDK is importable. Used by the ADK agent and the
platform-status endpoint.
"""

from __future__ import annotations

from app.config import settings
from app.services.fivetran_mcp import MCP_INVESTIGATION_TOOLS
from app.services.fivetran_mcp_stdio import _mcp_env


def build_fivetran_mcp_toolset():
    """ADK MCPToolset → real fivetran/fivetran-mcp server over stdio."""
    from google.adk.tools.mcp_tool import McpToolset
    from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
    from mcp import StdioServerParameters

    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=settings.fivetran_mcp_command,
                args=settings.fivetran_mcp_args_list,
                env=_mcp_env(),
            ),
        ),
        tool_filter=list(MCP_INVESTIGATION_TOOLS),
    )


def adk_available() -> bool:
    """True when the ``google-adk`` SDK is importable in the current environment."""
    try:
        import google.adk  # noqa: F401

        return True
    except ImportError:
        return False

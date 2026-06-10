"""Real Model Context Protocol (stdio) client for github.com/fivetran/fivetran-mcp."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# GitHub fivetran-mcp (OpenAPI server) requires schema_file on every tool call.
_TOOL_SCHEMA_FILES: dict[str, str] = {
    "get_account_info": "open-api-definitions/account/get_account_info.json",
    "list_connections": "open-api-definitions/connections/list_connections.json",
    "get_connection_details": "open-api-definitions/connections/connection_details.json",
    "get_connection_state": "open-api-definitions/connections/connection_state.json",
    "list_destinations": "open-api-definitions/destinations/list_destinations.json",
    "get_connection_schema_config": "open-api-definitions/connections/connection_schema_config.json",
}

_CONNECTION_SCOPED_TOOLS = frozenset(
    {
        "get_connection_details",
        "get_connection_state",
        "get_connection_schema_config",
    }
)

_INVESTIGATION_TOOLS = (
    "get_connection_details",
    "get_connection_state",
    "get_connection_schema_config",
)


def build_tool_arguments(tool_name: str, connection_id: str | None = None) -> dict[str, Any]:
    """Build MCP tool arguments including the mandatory schema_file path."""
    schema_file = _TOOL_SCHEMA_FILES.get(tool_name)
    if not schema_file:
        raise ValueError(f"Unknown Fivetran MCP tool: {tool_name}")
    args: dict[str, Any] = {"schema_file": schema_file}
    if connection_id is not None and tool_name in _CONNECTION_SCOPED_TOOLS:
        args["connection_id"] = connection_id
    return args


def parse_mcp_payload(payload: dict[str, Any]) -> Any:
    """Parse JSON from a serialized MCP tool result."""
    if payload.get("is_error"):
        blocks = payload.get("content") or []
        text = _extract_text(blocks if isinstance(blocks, list) else [])
        raise RuntimeError(text or "MCP tool returned is_error")
    structured = payload.get("structured_content")
    if structured is not None:
        return structured
    text = payload.get("text", "")
    if text.startswith("Error:") or text.startswith("Fivetran API error"):
        raise RuntimeError(text)
    if not text.strip():
        return payload
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw_text": text}


def mcp_stdio_available() -> bool:
    """True when MCP SDK is installed and Fivetran credentials are configured."""
    if settings.mock_fivetran_mcp or not settings.fivetran_credentials_configured:
        return False
    try:
        import mcp  # noqa: F401

        return True
    except ImportError:
        return False


def _mcp_env() -> dict[str, str]:
    """Environment passed to the spawned MCP server: Fivetran credentials and write-mode flag."""
    return {
        "FIVETRAN_API_KEY": settings.fivetran_api_key or "",
        "FIVETRAN_API_SECRET": settings.fivetran_api_secret or "",
        "FIVETRAN_ALLOW_WRITES": "true" if settings.fivetran_allow_writes else "false",
    }


def _serialize_tool_result(result: Any) -> dict[str, Any]:
    """Normalise an MCP ``CallToolResult`` into a JSON-safe dict (content, structured, text)."""
    if getattr(result, "isError", False):
        return {
            "is_error": True,
            "content": [_content_block_to_dict(c) for c in getattr(result, "content", [])],
        }
    blocks: list[Any] = []
    for block in getattr(result, "content", []):
        blocks.append(_content_block_to_dict(block))
    structured = getattr(result, "structuredContent", None)
    return {
        "is_error": False,
        "content": blocks,
        "structured_content": structured,
        "text": _extract_text(blocks),
    }


def _content_block_to_dict(block: Any) -> dict[str, Any]:
    """Convert a single MCP content block to a dict, falling back to text/string forms."""
    if hasattr(block, "model_dump"):
        return block.model_dump()
    if hasattr(block, "text"):
        return {"type": "text", "text": block.text}
    return {"type": "unknown", "value": str(block)}


def _extract_text(blocks: list[Any]) -> str:
    """Concatenate the text of any text-bearing content blocks into a single string."""
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("text"):
            parts.append(str(block["text"]))
        elif isinstance(block, dict) and "text" in block.get("type", ""):
            parts.append(str(block.get("text", "")))
    return "\n".join(p for p in parts if p)


async def _call_tool_async(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Open an MCP stdio session, call ``tool_name``, and serialize the result."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=settings.fivetran_mcp_command,
        args=settings.fivetran_mcp_args_list,
        env=_mcp_env(),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            payload = _serialize_tool_result(result)
            payload["mcp_protocol"] = "Model Context Protocol"
            payload["mcp_transport"] = "stdio"
            payload["mcp_server"] = "github.com/fivetran/fivetran-mcp"
            payload["tool_name"] = tool_name
            payload["tool_arguments"] = arguments
            return payload


def call_fivetran_mcp_tool_stdio(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Synchronous wrapper for MCP tools/call over stdio."""
    return asyncio.run(_call_tool_async(tool_name, arguments))


async def _call_tools_batch_async(tool_calls: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Run multiple MCP tool calls in a single stdio session (one subprocess spawn)."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    if not tool_calls:
        return []

    params = StdioServerParameters(
        command=settings.fivetran_mcp_command,
        args=settings.fivetran_mcp_args_list,
        env=_mcp_env(),
    )

    results: list[dict[str, Any]] = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for tool_name, arguments in tool_calls:
                result = await session.call_tool(tool_name, arguments)
                payload = _serialize_tool_result(result)
                payload["mcp_protocol"] = "Model Context Protocol"
                payload["mcp_transport"] = "stdio"
                payload["mcp_server"] = "github.com/fivetran/fivetran-mcp"
                payload["tool_name"] = tool_name
                payload["tool_arguments"] = arguments
                results.append(payload)
    return results


def call_fivetran_mcp_tools_batch_stdio(tool_calls: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Synchronous wrapper for batched MCP tools/call over one stdio session."""
    return asyncio.run(_call_tools_batch_async(tool_calls))


async def list_mcp_tools_async() -> list[str]:
    """Open an MCP stdio session and return the server's advertised tool names (``tools/list``)."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=settings.fivetran_mcp_command,
        args=settings.fivetran_mcp_args_list,
        env=_mcp_env(),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            return [t.name for t in listed.tools]


def list_mcp_tools() -> list[str]:
    """Return the tool names the Fivetran MCP server exposes, or the known defaults if offline."""
    if not mcp_stdio_available():
        return list(_INVESTIGATION_TOOLS)
    try:
        return asyncio.run(list_mcp_tools_async())
    except Exception as exc:  # noqa: BLE001
        logger.warning("list_mcp_tools failed: %s", exc)
        return list(_INVESTIGATION_TOOLS)

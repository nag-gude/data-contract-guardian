"""Data Contract Guardian — ADK chat agent for Agent Builder playground.

Pattern aligned with consentops-agent (prabhakaran-jm/consentops-agent):
- Local `adk web`: native Fivetran MCP via uvx + Cloud Run FunctionTools
- Agent Engine: MCP off by default; Fivetran tools proxy through Cloud Run /api/agent/fivetran
"""

from __future__ import annotations

import os
from pathlib import Path

import requests
from google.adk.agents import Agent
from google.adk.tools.function_tool import FunctionTool

_AGENT_DIR = Path(__file__).resolve().parent
_INSTRUCTION_PATH = _AGENT_DIR / "instructions.txt"
_GUARDIAN_API = os.environ.get(
    "GUARDIAN_API_BASE_URL",
    "https://data-contract-guardian-api-920722415791.us-central1.run.app",
).rstrip("/")
_GUARDIAN_UI = os.environ.get(
    "GUARDIAN_UI_BASE_URL",
    "https://data-contract-guardian-ui-920722415791.us-central1.run.app",
).rstrip("/")

FIVETRAN_READ_ONLY_TOOLS = (
    "get_account_info",
    "list_connections",
    "get_connection_details",
    "get_connection_state",
    "get_connection_schema_config",
    "list_destinations",
)

_LIST_CONNECTIONS_SCHEMA = "open-api-definitions/connections/list_connections.json"
_instruction = _INSTRUCTION_PATH.read_text(encoding="utf-8")
if _GUARDIAN_UI not in _instruction:
    _instruction = f"{_instruction}\n\nDashboard: {_GUARDIAN_UI}\n"


def _get_json(path: str, *, timeout: int = 120) -> dict:
    url = f"{_GUARDIAN_API}{path}"
    response = requests.get(url, timeout=timeout)
    if response.ok:
        return response.json()
    detail = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
    response.raise_for_status()
    return {"error": detail}


def _post_json(path: str, payload: dict | None = None, *, timeout: int = 120, retries: int = 2) -> dict:
    url = f"{_GUARDIAN_API}{path}"
    last_error: dict | str | None = None
    body = payload if payload is not None else {}
    for attempt in range(retries):
        try:
            response = requests.post(url, json=body, headers={"Content-Type": "application/json"}, timeout=timeout)
            if response.ok:
                return response.json()
            last_error = (
                response.json()
                if response.headers.get("content-type", "").startswith("application/json")
                else response.text
            )
            if response.status_code not in (500, 502, 503, 504) or attempt == retries - 1:
                response.raise_for_status()
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt == retries - 1:
                raise
    return {"error": f"Guardian API failed: {path}", "details": last_error}


def _post_fivetran_tool(tool: str, arguments: dict | None = None) -> dict:
    return _post_json("/api/agent/fivetran", {"tool": tool, "arguments": arguments or {}})


def guardianPlatformStatus() -> dict:
    """Read integration status: ADK, Gemini, Fivetran MCP, BigQuery, workflow counters."""
    return _get_json("/api/agent/platform")


def guardianDiscoverContract(contract_id: str) -> dict:
    """Validate a YAML contract and run read-only agent investigation (no incident open).

    Args:
        contract_id: Contract id such as network_cdr_freshness_v1.

    Returns:
        Validation details, MCP trace, root cause, ranked remediations, summary_for_agent.
    """
    cid = contract_id.strip()
    if not cid:
        raise ValueError("contract_id is required")
    return _post_json(f"/api/agent/discover/{cid}", {})


def guardianMcpDiscovery(connector_ref: str = "toll_donator") -> dict:
    """Run five read-only Fivetran MCP discovery tools for a connector slug.

    Args:
        connector_ref: Fivetran connection slug (default toll_donator).

    Returns:
        Discovery bundles, MCP trace, and summary_for_agent.
    """
    ref = connector_ref.strip() or "toll_donator"
    return _post_json(f"/api/agent/mcp-discovery?connector_ref={ref}", {})


def get_connection_details(connection_id: str) -> dict:
    """Read-only Fivetran connection details (no syncs or writes)."""
    return _post_fivetran_tool("get_connection_details", {"connection_id": connection_id.strip()})


def get_connection_state(connection_id: str) -> dict:
    """Read-only Fivetran sync/state snapshot (no sync triggers)."""
    return _post_fivetran_tool("get_connection_state", {"connection_id": connection_id.strip()})


def get_connection_schema_config(connection_id: str) -> dict:
    """Read-only Fivetran schema config for a connection."""
    return _post_fivetran_tool("get_connection_schema_config", {"connection_id": connection_id.strip()})


def get_account_info() -> dict:
    """Read-only Fivetran account metadata."""
    return _post_fivetran_tool("get_account_info")


def list_connections(schema_file: str = _LIST_CONNECTIONS_SCHEMA) -> dict:
    """List Fivetran connections in read-only mode."""
    return _post_fivetran_tool("list_connections", {"schema_file": schema_file})


def list_destinations() -> dict:
    """List Fivetran destinations (e.g. BigQuery) in read-only mode."""
    return _post_fivetran_tool("list_destinations")


def _fivetran_mcp_enabled() -> bool:
    return os.environ.get("ADK_FIVETRAN_MCP_ENABLED", "true").lower() in ("1", "true", "yes")


def _build_fivetran_mcp_toolset():
    if not _fivetran_mcp_enabled():
        return None
    api_key = os.environ.get("FIVETRAN_API_KEY", "").strip()
    api_secret = os.environ.get("FIVETRAN_API_SECRET", "").strip()
    if not api_key or not api_secret:
        return None
    try:
        from google.adk.tools.mcp_tool import McpToolset
        from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
        from mcp import StdioServerParameters

        command = os.environ.get("FIVETRAN_MCP_COMMAND", "uvx").strip() or "uvx"
        args_from_env = os.environ.get("FIVETRAN_MCP_ARGS", "").strip()
        if args_from_env:
            args = args_from_env.split()
        elif command in ("uvx", "uv"):
            args = ["--from", "git+https://github.com/fivetran/fivetran-mcp", "fivetran-mcp"]
        else:
            args = []

        return McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command=command,
                    args=args,
                    env={
                        "FIVETRAN_API_KEY": api_key,
                        "FIVETRAN_API_SECRET": api_secret,
                        "FIVETRAN_ALLOW_WRITES": "false",
                    },
                ),
                timeout=120,
            ),
            tool_filter=list(FIVETRAN_READ_ONLY_TOOLS),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Fivetran MCP toolset disabled (setup failed): {exc}")
        return None


def _build_cloud_fivetran_tools() -> list:
    return [
        FunctionTool(get_account_info),
        FunctionTool(list_connections),
        FunctionTool(get_connection_details),
        FunctionTool(get_connection_state),
        FunctionTool(get_connection_schema_config),
        FunctionTool(list_destinations),
    ]


def _build_tools() -> list:
    guardian_tools = [
        FunctionTool(guardianPlatformStatus),
        FunctionTool(guardianDiscoverContract),
        FunctionTool(guardianMcpDiscovery),
    ]
    mcp_toolset = _build_fivetran_mcp_toolset()
    if mcp_toolset is not None:
        return [mcp_toolset] + guardian_tools
    return _build_cloud_fivetran_tools() + guardian_tools


root_agent = Agent(
    name="guardian_assistant",
    model=os.environ.get("ADK_GEMINI_MODEL") or "gemini-2.5-flash",
    description=(
        "Read-only Data Contract Guardian: Fivetran MCP discovery, contract validation, "
        "evidence-grounded RCA. Human approval required in the web UI."
    ),
    instruction=_instruction,
    tools=_build_tools(),
)

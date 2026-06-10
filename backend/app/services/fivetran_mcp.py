"""
Fivetran MCP adapter for Data Contract Guardian.

Primary path: Model Context Protocol (stdio) → github.com/fivetran/fivetran-mcp
Demo path: realistic mock bundles when MOCK_FIVETRAN_MCP=true or credentials absent.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.schemas import EvidenceBundlePayload


def _iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _bundle(
    *,
    tool_name: str,
    connector_id: str,
    data: dict[str, Any],
    source: str = "fivetran_mcp",
) -> EvidenceBundlePayload:
    """Wrap a tool result in an ``EvidenceBundlePayload`` with a fresh unique bundle id."""
    return EvidenceBundlePayload(
        bundle_id=f"eb-{uuid.uuid4().hex[:10]}",
        source=source,
        tool_name=tool_name,
        connector_id=connector_id,
        data=data,
    )


# Fivetran source service per connector prefix, for realistic mock evidence.
_CONNECTOR_SERVICE = {
    "ft_airtable": "airtable",
}


def _service_for(connector_id: str) -> str:
    """Infer the Fivetran source service from a connector id prefix."""
    for prefix, service in _CONNECTOR_SERVICE.items():
        if connector_id.startswith(prefix):
            return service
    return "airtable"


def _mock_bundle(
    tool_name: str,
    connector_id: str,
    *,
    stale: bool,
    schema_drift: bool,
    drift_columns: list[str] | None = None,
    tables: list[str] | None = None,
) -> EvidenceBundlePayload:
    """
    Build a mock evidence bundle whose narrative is grounded in the *actual* failing checks:
      • ``stale``         — freshness failed → connector sync is paused / delayed / stale
      • ``schema_drift``  — schema/type failed → schema config reports a TYPE_MISMATCH
      • ``drift_columns`` — the specific column(s) that drifted, named in the error
      • ``tables``        — the table(s) this contract covers, surfaced as tables_enabled
    Both flags False yields a healthy-connector bundle. This keeps the Fivetran MCP evidence
    consistent with what the warehouse validation engine actually observed, for any table.
    """
    cols = drift_columns or []
    col_label = ", ".join(cols) if cols else "a typed column"
    enabled = tables or ["cdr"]

    resolved_id = connector_id if not connector_id.startswith("ft_") else "unprecedented_solidarity"

    if tool_name == "get_account_info":
        data = {
            "account_id": "fivetran-demo-account",
            "connection_count": 1,
            "destination_groups": ["network_warehouse"],
            "services": [_service_for(connector_id)],
            "read_only": True,
            "mcp_mode": "mock",
            "mcp_protocol": "Model Context Protocol (offline demo)",
        }
    elif tool_name == "list_connections":
        data = {
            "data": {
                "items": [
                    {
                        "id": resolved_id,
                        "service": _service_for(connector_id),
                        "schema": "network",
                        "paused": stale,
                        "status": {
                            "setup_state": "connected",
                            "sync_state": "paused" if stale else "scheduled",
                        },
                    }
                ]
            },
            "mcp_mode": "mock",
        }
    elif tool_name == "list_destinations":
        data = {
            "items": [
                {
                    "id": "bigquery_network",
                    "type": "bigquery",
                    "connections": [
                        {
                            "id": resolved_id,
                            "service": _service_for(connector_id),
                            "schema": "network",
                            "sync_state": "paused" if stale else "scheduled",
                        }
                    ],
                }
            ],
            "mcp_mode": "mock",
        }
    elif tool_name == "get_connection_details":
        data: dict[str, Any] = {
            "connector_id": connector_id,
            "sync_status": "failed" if stale else "healthy",
            "setup_state": "connected",
            "sync_state": "paused" if stale else "scheduled",
            "schema_status": "drift_detected" if schema_drift else "ready",
            "last_sync_completed_at": None if stale else _iso(),
            "service": _service_for(connector_id),
            "mcp_mode": "mock",
            "mcp_protocol": "Model Context Protocol (offline demo)",
        }
    elif tool_name == "get_connection_state":
        data = {
            "connector_id": connector_id,
            "sync_state": "paused" if stale else "scheduled",
            "update_state": "delayed" if stale else "on_schedule",
            "is_historical_sync": False,
            "mcp_mode": "mock",
        }
    elif tool_name == "get_connection_schema_config":
        data = {
            "connector_id": connector_id,
            "schema_notes": (
                f"{col_label} re-typed STRING after upstream change" if schema_drift else "schema stable"
            ),
            "recent_errors": (
                [f"TYPE_MISMATCH: {c} STRING vs numeric expected" for c in cols]
                if schema_drift
                else []
            ),
            "tables_enabled": enabled,
            "mcp_mode": "mock",
        }
    else:
        data = {"connector_id": connector_id, "mcp_mode": "mock"}

    return _bundle(tool_name=tool_name, connector_id=connector_id, data=data)


def _drift_flags(
    *,
    drift_mode: bool,
    failed_checks: list[str] | None,
) -> tuple[bool, bool]:
    """Resolve (stale, schema_drift) from explicit failed-check names, else legacy drift_mode."""
    if failed_checks is not None:
        stale = any(c == "freshness" for c in failed_checks)
        schema_drift = any(c.startswith("schema") for c in failed_checks)
        return stale, schema_drift
    return drift_mode, drift_mode


def _drift_columns(failed_checks: list[str] | None) -> list[str]:
    """Columns named by failed schema_type_<col> checks, for accurate evidence messages."""
    if not failed_checks:
        return []
    return [c[len("schema_type_"):] for c in failed_checks if c.startswith("schema_type_")]


def _fetch_connection_details_payload(connection_id: str) -> Any:
    from app.services.fivetran_mcp_stdio import (
        build_tool_arguments,
        call_fivetran_mcp_tool_stdio,
        parse_mcp_payload,
    )

    args = build_tool_arguments("get_connection_details", connection_id)
    raw = call_fivetran_mcp_tool_stdio("get_connection_details", args)
    return parse_mcp_payload(raw)


def _enrich_connection_state_bundle(
    *,
    tool_name: str,
    connector_id: str,
    connection_id: str,
    raw: dict[str, Any],
    error_text: str,
) -> EvidenceBundlePayload | None:
    """Derive connection state from details when /state returns 405 for standard connectors."""
    from app.services.fivetran_mcp_enrichment import (
        derive_connection_state_from_details,
        state_endpoint_unsupported,
    )

    if tool_name != "get_connection_state" or not state_endpoint_unsupported(error_text):
        return None

    try:
        details_payload = _fetch_connection_details_payload(connection_id)
        enriched = derive_connection_state_from_details(details_payload, connection_id)
        return _bundle(
            tool_name=tool_name,
            connector_id=connector_id,
            data={
                "fivetran_response": enriched,
                "resolved_connection_id": connection_id,
                "mcp_mode": "live_stdio_enriched",
                "read_only": not settings.fivetran_allow_writes,
                "fetched_at": _iso(),
                "fallback_reason": error_text[:300],
            },
        )
    except Exception:  # noqa: BLE001
        return None


def _connector_not_found(error_text: str) -> bool:
    return "404" in error_text and "Connector" in error_text


def _stdio_mcp_bundle(tool_name: str, connector_id: str) -> EvidenceBundlePayload:
    """Call the real Fivetran MCP server over stdio and wrap the result as an evidence bundle."""
    from app.services.fivetran_connection_resolver import (
        clear_resolution_cache,
        resolve_fivetran_connection_id,
    )
    from app.services.fivetran_mcp_stdio import (
        build_tool_arguments,
        call_fivetran_mcp_tool_stdio,
        parse_mcp_payload,
    )

    connection_id = resolve_fivetran_connection_id(connector_id)
    retried = False

    while True:
        args = build_tool_arguments(tool_name, connection_id)
        raw = call_fivetran_mcp_tool_stdio(tool_name, args)
        try:
            api_data = parse_mcp_payload(raw)
        except RuntimeError as exc:
            error_text = str(exc)
            if not retried and _connector_not_found(error_text):
                clear_resolution_cache(connector_id)
                retry_ref = connector_id if connector_id.startswith("ft_") else "ft_airtable_network"
                retry_id = resolve_fivetran_connection_id(retry_ref, skip_env_override=True)
                if retry_id != connection_id:
                    connection_id = retry_id
                    retried = True
                    continue
            enriched = _enrich_connection_state_bundle(
                tool_name=tool_name,
                connector_id=connector_id,
                connection_id=connection_id,
                raw=raw,
                error_text=error_text,
            )
            if enriched is not None:
                return enriched
            return _bundle(
                tool_name=tool_name,
                connector_id=connector_id,
                data={
                    **raw,
                    "is_error": True,
                    "error": error_text[:500],
                    "resolved_connection_id": connection_id,
                    "mcp_mode": "live_stdio_error",
                },
            )
        return _bundle(
            tool_name=tool_name,
            connector_id=connector_id,
            data={
                **raw,
                "fivetran_response": api_data,
                "resolved_connection_id": connection_id,
                "mcp_mode": "live_stdio",
                "read_only": not settings.fivetran_allow_writes,
                "fetched_at": _iso(),
            },
        )


def call_mcp_tool(
    tool_name: str,
    connector_id: str,
    *,
    drift_mode: bool = False,
    failed_checks: list[str] | None = None,
    tables: list[str] | None = None,
) -> EvidenceBundlePayload:
    """Invoke a Fivetran MCP tool and return a persisted evidence bundle."""
    if settings.mock_fivetran_mcp or not settings.fivetran_credentials_configured:
        stale, schema_drift = _drift_flags(drift_mode=drift_mode, failed_checks=failed_checks)
        return _mock_bundle(
            tool_name,
            connector_id,
            stale=stale,
            schema_drift=schema_drift,
            drift_columns=_drift_columns(failed_checks),
            tables=tables,
        )

    from app.services.fivetran_mcp_stdio import mcp_stdio_available

    if not mcp_stdio_available():
        return _bundle(
            tool_name=tool_name,
            connector_id=connector_id,
            data={
                "error": "MCP SDK unavailable; install mcp package",
                "mcp_mode": "error",
            },
        )

    try:
        return _stdio_mcp_bundle(tool_name, connector_id)
    except Exception as exc:  # noqa: BLE001
        return _bundle(
            tool_name=tool_name,
            connector_id=connector_id,
            data={
                "error": str(exc)[:500],
                "mcp_mode": "live_stdio_error",
                "mcp_protocol": "Model Context Protocol",
                "hint": "Verify FIVETRAN_API_KEY/SECRET and connector id; uvx fivetran-mcp reachable",
            },
        )


MCP_INVESTIGATION_TOOLS = (
    "get_connection_details",
    "get_connection_state",
    "get_connection_schema_config",
)


def fetch_investigation_evidence(
    connector_id: str,
    *,
    drift_mode: bool = False,
    failed_checks: list[str] | None = None,
    tables: list[str] | None = None,
) -> list[EvidenceBundlePayload]:
    """
    Multi-tool MCP evidence pack. When ``failed_checks`` is supplied, the mock narrative is
    grounded in the actual failing checks (freshness → stale sync, schema → type mismatch),
    and ``tables`` surfaces the specific table(s) the contract covers.
    """
    return [
        call_mcp_tool(
            tool, connector_id, drift_mode=drift_mode, failed_checks=failed_checks, tables=tables
        )
        for tool in MCP_INVESTIGATION_TOOLS
    ]


def mcp_transport_status(*, lightweight: bool = False) -> dict[str, Any]:
    """Report the active MCP transport (stdio/mock/unconfigured), server, and discovered tools."""
    from app.services.fivetran_mcp_stdio import list_mcp_tools, mcp_stdio_available
    from app.services.fivetran_pipeline_discovery import MCP_DISCOVERY_TOOLS

    discovered = list(MCP_DISCOVERY_TOOLS)
    if not lightweight and mcp_stdio_available():
        discovered = list_mcp_tools()

    return {
        "protocol": "Model Context Protocol",
        "transport": "stdio" if mcp_stdio_available() else ("mock" if settings.mock_fivetran_mcp else "unconfigured"),
        "server": "github.com/fivetran/fivetran-mcp",
        "command": settings.fivetran_mcp_command,
        "args": settings.fivetran_mcp_args_list,
        "tools": list(MCP_DISCOVERY_TOOLS),
        "investigation_tools": list(MCP_INVESTIGATION_TOOLS),
        "discovered_tools": discovered,
        "read_only": not settings.fivetran_allow_writes,
    }

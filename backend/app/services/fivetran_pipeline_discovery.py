"""Read-only Fivetran MCP pipeline discovery — five tools at scan time."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.schemas import EvidenceBundlePayload
from app.services.agent_response import build_mcp_trace
from app.services.fivetran_connection_resolver import (
    _connection_items,
    get_connector_context,
    resolve_fivetran_connection_id,
)
from app.services.fivetran_mcp import call_mcp_tool

MCP_DISCOVERY_TOOLS = (
    "get_account_info",
    "list_connections",
    "get_connection_details",
    "get_connection_state",
    "list_destinations",
)


def _skipped_bundle(tool_name: str, connector_id: str) -> EvidenceBundlePayload:
    from app.services.fivetran_mcp import _bundle

    return _bundle(
        tool_name=tool_name,
        connector_id=connector_id,
        data={
            "error": "Skipped — no connections from list_connections.",
            "is_error": True,
            "mcp_mode": "skipped",
        },
    )


def _primary_connection_id(items: list[dict[str, Any]], connector_ref: str | None) -> str | None:
    if connector_ref:
        resolved = resolve_fivetran_connection_id(connector_ref)
        if resolved and not resolved.startswith("ft_"):
            return resolved
    for item in items:
        if item.get("service") == "airtable":
            return str(item.get("id"))
    if items:
        cid = items[0].get("id")
        return str(cid) if cid else None
    return None


def _connection_items_from_bundle(bundle: EvidenceBundlePayload) -> list[dict[str, Any]]:
    if bundle.data.get("error") or bundle.data.get("is_error"):
        return []
    resp = bundle.data.get("fivetran_response") or bundle.data
    items = _connection_items(resp)
    if items:
        return items
    if bundle.tool_name == "list_connections" and isinstance(bundle.data.get("data"), dict):
        return _connection_items(bundle.data)
    return []


def _infer_health(item: dict[str, Any]) -> str:
    if item.get("paused"):
        return "offline"
    setup = str((item.get("status") or {}).get("setup_state", "")).lower()
    if setup and setup != "connected":
        return "warning"
    return "healthy"


def _build_lineage(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lineage: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        lineage.append(
            {
                "connector_alias": f"connector_{index + 1:02d}",
                "service": item.get("service") or "unknown",
                "schema": item.get("schema") or "—",
                "health": _infer_health(item),
                "connection_id": item.get("id"),
            }
        )
    return lineage


def _discovery_bundles_mock(ref: str) -> list[EvidenceBundlePayload]:
    """Mock discovery path — one bundle per tool."""
    bundles: list[EvidenceBundlePayload] = []
    bundles.append(call_mcp_tool("get_account_info", ref))
    list_bundle = call_mcp_tool("list_connections", ref)
    bundles.append(list_bundle)

    items = _connection_items_from_bundle(list_bundle)
    primary_id = _primary_connection_id(items, ref)

    if primary_id:
        bundles.append(call_mcp_tool("get_connection_details", ref))
        bundles.append(call_mcp_tool("get_connection_state", ref))
    else:
        bundles.append(_skipped_bundle("get_connection_details", ref))
        bundles.append(_skipped_bundle("get_connection_state", ref))

    bundles.append(call_mcp_tool("list_destinations", ref))
    return bundles


def _discovery_bundles_stdio(ref: str) -> list[EvidenceBundlePayload]:
    """Live discovery — all tools in one MCP stdio session."""
    from datetime import datetime, timezone

    from app.services.fivetran_connection_resolver import resolve_fivetran_connection_id
    from app.services.fivetran_mcp import _bundle
    from app.services.fivetran_mcp_enrichment import derive_connection_state_from_details, state_endpoint_unsupported
    from app.services.fivetran_mcp_stdio import (
        build_tool_arguments,
        call_fivetran_mcp_tools_batch_stdio,
        parse_mcp_payload,
    )

    connection_id = resolve_fivetran_connection_id(ref)
    tool_names = list(MCP_DISCOVERY_TOOLS)
    specs: list[tuple[str, dict]] = []
    for tool in tool_names:
        args = build_tool_arguments(tool, connection_id if tool in {"get_connection_details", "get_connection_state"} else None)
        specs.append((tool, args))

    raw_results = call_fivetran_mcp_tools_batch_stdio(specs)
    details_payload: dict | None = None
    bundles: list[EvidenceBundlePayload] = []
    now = datetime.now(timezone.utc).isoformat()

    for tool_name, raw in zip(tool_names, raw_results, strict=True):
        try:
            api_data = parse_mcp_payload(raw)
            if tool_name == "get_connection_details":
                details_payload = api_data
            bundles.append(
                _bundle(
                    tool_name=tool_name,
                    connector_id=ref,
                    data={
                        **raw,
                        "fivetran_response": api_data,
                        "resolved_connection_id": connection_id,
                        "mcp_mode": "live_stdio",
                        "read_only": not settings.fivetran_allow_writes,
                        "fetched_at": now,
                    },
                )
            )
        except RuntimeError as exc:
            error_text = str(exc)
            if (
                tool_name == "get_connection_state"
                and details_payload is not None
                and state_endpoint_unsupported(error_text)
            ):
                bundles.append(
                    _bundle(
                        tool_name=tool_name,
                        connector_id=ref,
                        data={
                            "fivetran_response": derive_connection_state_from_details(
                                details_payload, connection_id
                            ),
                            "resolved_connection_id": connection_id,
                            "mcp_mode": "live_stdio_enriched",
                            "read_only": not settings.fivetran_allow_writes,
                            "fetched_at": now,
                            "fallback_reason": error_text[:300],
                        },
                    )
                )
                continue
            bundles.append(
                _bundle(
                    tool_name=tool_name,
                    connector_id=ref,
                    data={
                        **raw,
                        "is_error": True,
                        "error": error_text[:500],
                        "resolved_connection_id": connection_id,
                        "mcp_mode": "live_stdio_error",
                    },
                )
            )

    return bundles


def run_mcp_discovery(connector_ref: str | None = "ft_airtable_network") -> dict[str, Any]:
    """Execute read-only Fivetran MCP discovery tools and return trace + lineage."""
    ref = connector_ref or "ft_airtable_network"

    if settings.use_real_fivetran and settings.fivetran_credentials_configured:
        from app.services.fivetran_mcp_stdio import mcp_stdio_available

        bundles = _discovery_bundles_stdio(ref) if mcp_stdio_available() else _discovery_bundles_mock(ref)
    else:
        bundles = _discovery_bundles_mock(ref)

    list_bundle = next((b for b in bundles if b.tool_name == "list_connections"), None)
    items = _connection_items_from_bundle(list_bundle) if list_bundle else []
    primary_id = _primary_connection_id(items, ref)

    trace = build_mcp_trace(bundles)
    source = "mcp_stdio" if settings.use_real_fivetran else "mock"

    return {
        "ok": True,
        "discovery_source": source,
        "tools_run": len(trace),
        "mcp_trace": trace,
        "evidence_bundles": [b.model_dump() for b in bundles],
        "pipeline_lineage": _build_lineage(items),
        "primary_connection_id": primary_id,
        "connector_context": get_connector_context(ref),
    }

"""Fallback enrichment when Fivetran MCP tools return empty or unsupported responses."""

from __future__ import annotations

from typing import Any


def state_endpoint_unsupported(error_text: str) -> bool:
    """True when /connections/{id}/state is not supported for this connector type."""
    lowered = error_text.lower()
    return (
        "405" in lowered
        or "method not allowed" in lowered
        or "only supported for function" in lowered
        or "connection sdk" in lowered
    )


def _unwrap_fivetran_data(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("data"), dict):
        inner = payload["data"]
        if isinstance(inner.get("data"), dict):
            return inner["data"]
        return inner
    return payload


def derive_connection_state_from_details(details_payload: Any, connection_id: str) -> dict[str, Any]:
    """Build a get_connection_state-shaped object from get_connection_details / list_connections."""
    item = _unwrap_fivetran_data(details_payload)
    status = item.get("status") if isinstance(item.get("status"), dict) else {}
    return {
        "connection_id": connection_id,
        "service": item.get("service"),
        "schema": item.get("schema"),
        "sync_state": status.get("sync_state", "unknown"),
        "setup_state": status.get("setup_state", "unknown"),
        "update_state": status.get("update_state"),
        "succeeded_at": item.get("succeeded_at"),
        "failed_at": item.get("failed_at"),
        "paused": item.get("paused", False),
        "enriched_from": "get_connection_details",
        "note": (
            "Fivetran /connections/{id}/state is only supported for Function and SDK connectors; "
            "state derived from connection details."
        ),
    }


def derive_connection_state_from_list_item(item: dict[str, Any], connection_id: str) -> dict[str, Any]:
    """Build state from a list_connections item when details are unavailable."""
    status = item.get("status") if isinstance(item.get("status"), dict) else {}
    return {
        "connection_id": connection_id,
        "service": item.get("service"),
        "schema": item.get("schema"),
        "sync_state": status.get("sync_state", "unknown"),
        "setup_state": status.get("setup_state", "unknown"),
        "update_state": status.get("update_state"),
        "succeeded_at": item.get("succeeded_at"),
        "failed_at": item.get("failed_at"),
        "paused": item.get("paused", False),
        "enriched_from": "list_connections",
        "note": (
            "Fivetran /connections/{id}/state is only supported for Function and SDK connectors; "
            "state derived from list_connections."
        ),
    }

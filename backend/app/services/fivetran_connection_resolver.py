"""Resolve friendly contract connector aliases to real Fivetran connection ids."""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_RESOLUTION_CACHE: dict[str, str] = {}

_ALIAS_HINTS: dict[str, dict[str, str]] = {
    "ft_airtable_network": {"service": "airtable", "schema_contains": "network"},
}


def clear_resolution_cache(connector_ref: str | None = None) -> None:
    """Drop cached alias resolution (e.g. after a 404 from a stale env override)."""
    if connector_ref:
        _RESOLUTION_CACHE.pop(connector_ref, None)
    else:
        _RESOLUTION_CACHE.clear()


def resolve_fivetran_connection_id(connector_ref: str, *, skip_env_override: bool = False) -> str:
    """
    Map contract ``fivetran_connector_id`` to a Fivetran REST connection id.

    ``FIVETRAN_CONNECTION_ID`` (from ``.env`` / ``terraform.tfvars``) may be a dashboard slug
    (``toll_donator``) or a schema/name hint (``hackathon``). Hints are matched via
    ``list_connections`` — they are **never** sent to the Fivetran API as raw connection ids.
    """
    ref = (connector_ref or "ft_airtable_network").strip()
    items = _fetch_connection_items()

    if not skip_env_override and ref in _RESOLUTION_CACHE:
        cached = _RESOLUTION_CACHE[ref]
        if _is_known_connection_id(cached, items):
            return cached
        clear_resolution_cache(ref)

    env_ref = (settings.fivetran_connection_id or "").strip()

    if env_ref and not skip_env_override:
        matched = _match_connection_ref(env_ref, items)
        if matched:
            _RESOLUTION_CACHE[ref] = matched
            logger.info("Resolved FIVETRAN_CONNECTION_ID %r → %s", env_ref, matched)
            return matched

    if not ref.startswith("ft_"):
        matched = _match_connection_ref(ref, items)
        if matched:
            _RESOLUTION_CACHE[ref] = matched
            logger.info("Resolved connector ref %r → %s", ref, matched)
            return matched

    if ref.startswith("ft_"):
        resolved = _match_alias(
            ref,
            items,
            extra_schema_hint=env_ref if env_ref and not skip_env_override else None,
        )
        if resolved:
            _RESOLUTION_CACHE[ref] = resolved
            logger.info("Resolved Fivetran alias %s → %s", ref, resolved)
            return resolved

    sole = _sole_airtable_connector(items)
    if sole:
        _RESOLUTION_CACHE[ref] = sole
        logger.info("Resolved %s → sole Airtable connector %s", ref, sole)
        return sole

    logger.warning(
        "Could not resolve connector ref %r (env=%r, connections=%d)",
        ref,
        env_ref or None,
        len(items),
    )
    return ref


def get_connector_context(connector_ref: str) -> dict[str, Any]:
    """Connector resolution metadata for agent traces and platform status."""
    items = _fetch_connection_items()
    env_ref = (settings.fivetran_connection_id or "").strip()
    resolved = resolve_fivetran_connection_id(connector_ref)
    matched = next((c for c in items if str(c.get("id")) == resolved), None)

    config_source = "auto_resolve"
    if env_ref:
        config_source = "FIVETRAN_CONNECTION_ID (.env / terraform.tfvars)"

    return {
        "contract_connector_ref": connector_ref,
        "configured_connection_ref": env_ref or None,
        "resolved_connection_id": resolved,
        "resolution_valid": _is_known_connection_id(resolved, items),
        "config_source": config_source,
        "connection_service": matched.get("service") if matched else None,
        "connection_schema": matched.get("schema") if matched else None,
        "fivetran_ui_schema_tab": (
            f"https://fivetran.com/dashboard/connectors/{resolved}/schema"
            if resolved and _is_known_connection_id(resolved, items)
            else None
        ),
        "fivetran_ui_sync_logs": (
            f"https://fivetran.com/dashboard/connectors/{resolved}/logs"
            if resolved and _is_known_connection_id(resolved, items)
            else None
        ),
    }


def _fetch_connection_items() -> list[dict[str, Any]]:
    from app.services.fivetran_mcp_stdio import (
        build_tool_arguments,
        call_fivetran_mcp_tool_stdio,
        parse_mcp_payload,
    )

    try:
        raw = call_fivetran_mcp_tool_stdio("list_connections", build_tool_arguments("list_connections"))
        data = parse_mcp_payload(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Fivetran list_connections failed: %s", exc)
        return []
    return _connection_items(data)


def _is_known_connection_id(connection_id: str, connections: list[dict[str, Any]]) -> bool:
    return any(str(c.get("id")) == connection_id for c in connections)


def _sole_airtable_connector(connections: list[dict[str, Any]]) -> str | None:
    airtable = [c for c in connections if c.get("service") == "airtable"]
    if len(airtable) == 1:
        cid = airtable[0].get("id")
        return str(cid) if cid else None
    return None


def _match_connection_ref(ref: str, connections: list[dict[str, Any]]) -> str | None:
    """Match env ref to a connection by slug, schema, or display name."""
    if not ref:
        return None
    ref_lower = ref.lower()

    for conn in connections:
        if str(conn.get("id")) == ref:
            return str(conn.get("id"))

    for conn in connections:
        if str(conn.get("schema") or "").lower() == ref_lower:
            return str(conn.get("id"))

    for conn in connections:
        if str(conn.get("name") or "").lower() == ref_lower:
            return str(conn.get("id"))

    for conn in connections:
        schema = str(conn.get("schema") or "").lower()
        conn_id = str(conn.get("id") or "").lower()
        if ref_lower in schema or ref_lower in conn_id:
            return str(conn.get("id"))

    return None


def _connection_items(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    if "data" in data and isinstance(data["data"], dict):
        items = data["data"].get("items")
        if isinstance(items, list):
            return [i for i in items if isinstance(i, dict)]
    if "connections" in data and isinstance(data["connections"], list):
        return [i for i in data["connections"] if isinstance(i, dict)]
    return []


def _match_alias(
    alias: str,
    connections: list[dict[str, Any]],
    *,
    extra_schema_hint: str | None = None,
) -> str | None:
    hints = _ALIAS_HINTS.get(alias, {})
    service = hints.get("service")
    schema_needle = (hints.get("schema_contains") or "").lower()

    candidates = connections
    if service:
        candidates = [c for c in candidates if c.get("service") == service]

    needles = [n for n in (schema_needle, (extra_schema_hint or "").lower()) if n]
    for needle in needles:
        narrowed = [
            c
            for c in candidates
            if needle in str(c.get("schema") or "").lower()
            or needle in str(c.get("id") or "").lower()
        ]
        if narrowed:
            candidates = narrowed
            break

    if len(candidates) == 1:
        return str(candidates[0].get("id"))
    if candidates:
        return str(candidates[0].get("id"))
    return None

"""Direct Fivetran REST API helpers for approved remediation side effects."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_BASE = "https://api.fivetran.com/v1"


def _auth() -> tuple[str, str] | None:
    if not settings.fivetran_api_key or not settings.fivetran_api_secret:
        return None
    return settings.fivetran_api_key, settings.fivetran_api_secret


def _request(method: str, path: str, *, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
    auth = _auth()
    if not auth:
        raise RuntimeError("Fivetran API credentials not configured")
    url = f"{_BASE}{path}"
    with httpx.Client(timeout=30.0) as client:
        r = client.request(method, url, auth=auth, json=json_body)
    if r.status_code >= 400:
        raise RuntimeError(f"Fivetran API {r.status_code}: {r.text[:300]}")
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {"raw": r.text}


def resume_connection(connection_id: str) -> dict[str, Any]:
    """Unpause a Fivetran connection."""
    return _request("PATCH", f"/connections/{connection_id}", json_body={"paused": False})


def trigger_sync(connection_id: str, *, force: bool = True) -> dict[str, Any]:
    """Trigger an incremental sync for a connection."""
    body = {"force": force} if force else {}
    return _request("POST", f"/connections/{connection_id}/sync", json_body=body)


def get_connection_details(connection_id: str) -> dict[str, Any]:
    """Fetch connection details including succeeded_at."""
    return _request("GET", f"/connections/{connection_id}")

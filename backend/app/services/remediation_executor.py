"""Execute the top-ranked remediation after human approval."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.schemas import DataContract, MockWarehouseState, RemediationOption
from app.services.fivetran_connection_resolver import resolve_fivetran_connection_id
from app.services.validation_engine import get_mock_warehouse_state, set_mock_warehouse_state, validate_contract


def _top_remediation(ranked: list[RemediationOption] | list[dict[str, Any]]) -> RemediationOption | None:
    if not ranked:
        return None
    first = ranked[0]
    if isinstance(first, RemediationOption):
        return sorted(ranked, key=lambda r: r.rank)[0]
    parsed = [RemediationOption(**r) if isinstance(r, dict) else r for r in ranked]
    return sorted(parsed, key=lambda r: r.rank)[0]


def _title_lower(title: str) -> str:
    return title.lower()


def _is_sync_remediation(title: str) -> bool:
    t = _title_lower(title)
    return any(k in t for k in ("sync", "resume paused", "catch-up"))


def _is_schema_remediation(title: str) -> bool:
    t = _title_lower(title)
    return "safe_cast" in t or "schema" in t or "missing columns" in t


def _apply_mock_freshness_fix(contract: DataContract) -> None:
    state = get_mock_warehouse_state(contract.contract_id)
    if not state:
        return
    set_mock_warehouse_state(
        contract.contract_id,
        state.model_copy(update={"last_synced_at": datetime.now(timezone.utc).isoformat()}),
    )


def _apply_mock_schema_fix(contract: DataContract, title: str) -> bool:
    state = get_mock_warehouse_state(contract.contract_id)
    if not state or not contract.schema_block:
        return False
    match = re.search(r"`(\w+)`", title)
    if not match:
        return False
    col = match.group(1)
    expected = contract.schema_block.column_types.get(col)
    if not expected:
        return False
    types = dict(state.column_types)
    types[col] = expected
    set_mock_warehouse_state(contract.contract_id, state.model_copy(update={"column_types": types}))
    return True


def _execute_live_sync(connector_ref: str, title: str) -> dict[str, Any]:
    from app.services.fivetran_rest import get_connection_details, resume_connection, trigger_sync

    connection_id = resolve_fivetran_connection_id(connector_ref)
    steps: list[str] = []

    if "resume" in _title_lower(title) or "paused" in _title_lower(title):
        resume_connection(connection_id)
        steps.append(f"resumed connection {connection_id}")

    trigger_sync(connection_id, force=True)
    steps.append(f"triggered sync for {connection_id}")

    details = get_connection_details(connection_id)
    succeeded_at = (details.get("data") or {}).get("succeeded_at")
    return {
        "mode": "live_fivetran_rest",
        "connection_id": connection_id,
        "steps": steps,
        "succeeded_at": succeeded_at,
        "summary": "; ".join(steps),
        "await_verification": True,
    }


def execute_top_remediation(
    contract: DataContract,
    ranked_remediations: list[RemediationOption] | list[dict[str, Any]],
    *,
    connector_ref: str | None = None,
) -> dict[str, Any]:
    """Run side effects for the highest-ranked remediation. Returns an execution report."""
    top = _top_remediation(ranked_remediations)
    if not top:
        return {"executed": False, "summary": "No remediation ranked", "await_verification": False}

    title = top.title
    ref = connector_ref or contract.fivetran_connector_id or "ft_airtable_network"

    if _is_sync_remediation(title):
        if settings.use_live_bigquery and settings.fivetran_credentials_configured:
            try:
                return {"executed": True, **_execute_live_sync(ref, title)}
            except Exception as exc:  # noqa: BLE001
                return {
                    "executed": False,
                    "summary": f"Fivetran sync trigger failed: {exc}",
                    "await_verification": False,
                    "error": str(exc)[:300],
                }
        _apply_mock_freshness_fix(contract)
        return {
            "executed": True,
            "mode": "mock_warehouse",
            "summary": "Refreshed mock warehouse last_synced_at",
            "await_verification": False,
        }

    if _is_schema_remediation(title) and not settings.use_live_bigquery:
        fixed = _apply_mock_schema_fix(contract, title)
        return {
            "executed": fixed,
            "mode": "mock_warehouse",
            "summary": "Corrected mock column type" if fixed else "Schema remediation requires manual dbt/MR in live mode",
            "await_verification": False,
        }

    return {
        "executed": False,
        "mode": "advisory",
        "summary": f"Coordination-only remediation: {title}",
        "await_verification": False,
    }


def verify_with_retry(
    contract: DataContract,
    *,
    await_verification: bool = False,
    timeout_sec: int = 90,
    interval_sec: int = 10,
) -> tuple[bool, dict[str, Any], int]:
    """Re-validate; poll when a live sync was triggered and BigQuery may lag."""
    if not await_verification:
        passed, details = validate_contract(contract)
        return passed, details, 0

    deadline = time.monotonic() + timeout_sec
    attempts = 0
    last_details: dict[str, Any] = {}
    while time.monotonic() < deadline:
        attempts += 1
        passed, last_details = validate_contract(contract)
        if passed:
            return True, last_details, attempts
        freshness = next((c for c in last_details.get("checks", []) if c.get("name") == "freshness"), None)
        if freshness and freshness.get("passed"):
            return True, last_details, attempts
        time.sleep(interval_sec)

    passed, last_details = validate_contract(contract)
    return passed, last_details, attempts

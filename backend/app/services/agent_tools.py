"""Agent tools exposed to Gemini / Google Cloud Agent Builder (ADK-compatible)."""

from __future__ import annotations

from typing import Any

from app.services.contracts_loader import get_contract
from app.services.fivetran_mcp import fetch_investigation_evidence
from app.services.validation_engine import validate_contract


def validate_data_contract(contract_id: str) -> dict[str, Any]:
    """
    Run data contract validation against warehouse state (BigQuery mock or live).

    Returns structured checks[] comparing YAML contract rules to observed warehouse columns,
    types, and freshness.
    """
    contract = get_contract(contract_id)
    if not contract:
        return {"ok": False, "error": f"contract not found: {contract_id}"}
    passed, details = validate_contract(contract)
    return {"ok": True, "contract_id": contract_id, "passed": passed, "details": details}


def fetch_fivetran_mcp_evidence(
    connector_id: str,
    drift_mode: bool = True,
    failed_checks: list[str] | None = None,
    tables: list[str] | None = None,
) -> dict[str, Any]:
    """
    Call Fivetran MCP tools (get_connection_details, get_connection_state, get_connection_schema_config)
    and return evidence bundles for incident grounding.

    When ``failed_checks`` (validation check names) is provided, the mock evidence narrative is
    grounded in the real failing checks rather than a blanket "everything is broken" story.
    ``tables`` names the table(s) the contract covers so the evidence references the right mart.
    """
    bundles = fetch_investigation_evidence(
        connector_id, drift_mode=drift_mode, failed_checks=failed_checks, tables=tables
    )
    return {
        "ok": True,
        "connector_id": connector_id,
        "tool_count": len(bundles),
        "bundles": [b.model_dump() for b in bundles],
    }


def failed_check_names(validation_details: dict[str, Any]) -> list[str]:
    """Names of checks that did not pass — used to ground MCP evidence and remediations."""
    return [c.get("name", "") for c in validation_details.get("checks", []) if not c.get("passed")]


def classify_incident_severity(validation_details: dict[str, Any]) -> dict[str, Any]:
    """Classify incident severity from failed validation checks."""
    failed = [c for c in validation_details.get("checks", []) if not c.get("passed")]
    if any(c.get("name", "").startswith("schema") for c in failed):
        severity = "critical"
    elif any(c.get("name") == "freshness" for c in failed):
        severity = "high"
    elif failed:
        severity = "medium"
    else:
        severity = "low"
    return {"severity": severity, "failed_checks": [c.get("name") for c in failed]}

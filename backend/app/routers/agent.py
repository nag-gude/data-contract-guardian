"""Agent router — the agentic surface of the API.

Exposes multi-step investigation, pipeline orchestration, read-only discovery, and platform status.
Approval and execution are intentionally routed through ``/api/incidents/approve-remediation`` or
the UI — not through agent endpoints.
"""

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

from app.schemas import AgentRunBody, AgentRunResult
from app.services.agent_orchestrator import platform_status, run_agent_investigation
from app.services.agent_response import (
    AGENT_DISCLAIMER,
    CAPABILITY_INVESTIGATE,
    CAPABILITY_MCP_DISCOVERY,
    CAPABILITY_PIPELINE,
    build_mcp_trace,
    build_summary_for_agent,
    reject_execution_shaped_body,
)
from app.services.fivetran_pipeline_discovery import MCP_DISCOVERY_TOOLS, run_mcp_discovery
from app.services.contracts_loader import get_contract, load_all_contracts
from app.services.incident_service import create_incident_for_failure
from app.services.validation_engine import validate_contract
from app.services.validation_runs import persist_validation_run

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/platform")
def get_platform():
    """Integration status: Agent Builder, Gemini, Fivetran MCP, BigQuery, and workflow counters."""
    return platform_status()


@router.post("/mcp-discovery")
def mcp_discovery(connector_ref: str = "ft_airtable_network"):
    """
    Read-only Fivetran MCP discovery: account, connections, connection state, destinations.
    Mirrors the five-tool scan used in hackathon demos — no incidents or writes.
    """
    result = run_mcp_discovery(connector_ref)
    return {
        "capability": CAPABILITY_MCP_DISCOVERY,
        "disclaimer": AGENT_DISCLAIMER,
        "connector_ref": connector_ref,
        "tools": list(MCP_DISCOVERY_TOOLS),
        **result,
    }


@router.post("/discover/{contract_id}")
def discover_contract(contract_id: str, body: dict[str, Any] | None = Body(default=None)):
    """
    Read-only discovery: validate contract + Fivetran MCP evidence. Never opens incidents.
    Intended for Agent Builder / ADK chat — execution stays in the UI.
    """
    err = reject_execution_shaped_body(body)
    if err:
        raise HTTPException(400, detail=err)

    contract = get_contract(contract_id)
    if not contract:
        raise HTTPException(404, detail="contract not found")

    passed, details = validate_contract(contract)
    persist_validation_run(contract.contract_id, passed, details)
    investigation = run_agent_investigation(contract, details, validation_passed=passed)
    bundles = [
        b.model_dump() if hasattr(b, "model_dump") else b for b in investigation.get("evidence_bundles", [])
    ]
    trace = build_mcp_trace(bundles)
    return {
        "capability": CAPABILITY_INVESTIGATE,
        "disclaimer": AGENT_DISCLAIMER,
        "contract_id": contract_id,
        "validation_passed": passed,
        "validation_details": details,
        "connector_context": investigation.get("connector_context"),
        "schema_investigation": investigation.get("schema_investigation"),
        "severity": investigation.get("severity"),
        "root_cause": investigation.get("root_cause"),
        "confidence": investigation.get("confidence"),
        "stakeholder_summary": investigation.get("stakeholder_summary"),
        "transcript": investigation.get("transcript", []),
        "evidence_bundles": bundles,
        "mcp_trace": trace,
        "ranked_remediations": investigation.get("ranked_remediations", []),
        "summary_for_agent": build_summary_for_agent(
            contract_id=contract_id,
            validation_passed=passed,
            validation_details=details,
            severity=investigation.get("severity"),
            incident_id=None,
            mcp_trace=trace,
            ranked_remediations=investigation.get("ranked_remediations"),
        ),
    }


@router.post("/investigate", response_model=AgentRunResult)
async def investigate(request: Request):
    """
    Run the multi-step agent investigation for one contract.
    Does not persist an incident unless ``open_incident=true`` (use UI workflow for HITL).
    """
    raw = await request.json()
    if not isinstance(raw, dict):
        raise HTTPException(400, detail="JSON object required")
    err = reject_execution_shaped_body(raw)
    if err:
        raise HTTPException(400, detail=err)
    body = AgentRunBody.model_validate(raw)

    contract = get_contract(body.contract_id)
    if not contract:
        raise HTTPException(404, detail="contract not found")

    passed, details = validate_contract(contract)
    if body.require_failure and passed:
        raise HTTPException(400, detail="contract passed validation; seed failing state first")

    result = run_agent_investigation(contract, details, validation_passed=passed)
    incident_id = None
    if not passed and body.open_incident:
        inc = create_incident_for_failure(contract, passed, details, investigation=result)
        incident_id = inc.id if inc else None

    bundles = [
        b.model_dump() if hasattr(b, "model_dump") else b for b in result.get("evidence_bundles", [])
    ]
    trace = build_mcp_trace(bundles)
    base = AgentRunResult(
        contract_id=body.contract_id,
        validation_passed=passed,
        validation_details=details,
        incident_id=incident_id,
        transcript=result.get("transcript", []),
        evidence_bundles=bundles,
        connector_context=result.get("connector_context"),
        schema_investigation=result.get("schema_investigation"),
        root_cause=result.get("root_cause"),
        confidence=result.get("confidence"),
        stakeholder_summary=result.get("stakeholder_summary"),
        severity=result.get("severity"),
        ranked_remediations=result.get("ranked_remediations", []),
        action_fingerprint=result.get("action_fingerprint"),
        orchestrator=result.get("orchestrator"),
        platform=result.get("platform"),
        capability=CAPABILITY_INVESTIGATE,
        disclaimer=AGENT_DISCLAIMER,
        mcp_trace=trace,
        summary_for_agent=build_summary_for_agent(
            contract_id=body.contract_id,
            validation_passed=passed,
            validation_details=details,
            severity=result.get("severity"),
            incident_id=incident_id,
            mcp_trace=trace,
            ranked_remediations=result.get("ranked_remediations"),
        ),
    )
    return base


@router.post("/run-pipeline")
def run_pipeline(open_incidents: bool = True):
    """
    End-to-end pipeline:
    validate all contracts → agent investigation → open incidents on failure.
    """
    outcomes: list[dict[str, Any]] = []
    for contract in load_all_contracts():
        passed, details = validate_contract(contract)
        persist_validation_run(contract.contract_id, passed, details)
        investigation = run_agent_investigation(contract, details, validation_passed=passed)
        incident_id = None
        if not passed and open_incidents:
            inc = create_incident_for_failure(contract, passed, details, investigation=investigation)
            incident_id = inc.id if inc else None
        bundles = [
            b.model_dump() if hasattr(b, "model_dump") else b
            for b in investigation.get("evidence_bundles", [])
        ]
        trace = build_mcp_trace(bundles)
        outcomes.append(
            {
                "contract_id": contract.contract_id,
                "validation_passed": passed,
                "incident_id": incident_id,
                "severity": investigation.get("severity"),
                "transcript_steps": len(investigation.get("transcript", [])),
                "mcp_bundles": len(bundles),
                "mcp_trace": trace,
                "failed_checks": [
                    c.get("name") for c in details.get("checks", []) if not c.get("passed")
                ],
            }
        )
    failed_n = sum(1 for o in outcomes if not o["validation_passed"])
    return {
        "ok": True,
        "capability": CAPABILITY_PIPELINE,
        "disclaimer": AGENT_DISCLAIMER,
        "summary_for_agent": {
            "contracts_total": len(outcomes),
            "contracts_failed": failed_n,
            "incidents_opened": sum(1 for o in outcomes if o.get("incident_id")),
            "instruction": "Open incidents in the UI to approve fingerprinted remediations.",
        },
        "platform": platform_status(),
        "outcomes": outcomes,
    }

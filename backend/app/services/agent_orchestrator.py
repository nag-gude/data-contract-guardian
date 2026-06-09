"""Multi-step agent orchestrator for data-contract incident investigation.

Implements the agent mission:
  PLAN → Fivetran MCP tools → validate → SYNTH (RCA) → PROPOSE → AWAIT approval

When ``google-adk`` is installed and ``USE_AGENT_BUILDER=true``, delegates to the managed ADK
agent in ``agent_builder/``. Otherwise runs an equivalent deterministic tool loop with Gemini.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.schemas import DataContract, EvidenceBundlePayload, utc_now
from app.services.agent_rca import (
    build_ranked_remediations,
    fingerprint_from_payload,
    generate_investigation_plan,
    generate_rca_and_root_cause,
)
from app.services.agent_tools import (
    classify_incident_severity,
    failed_check_names,
    fetch_fivetran_mcp_evidence,
    validate_data_contract,
)
from app.services.fivetran_connection_resolver import get_connector_context
from app.services.fivetran_mcp import MCP_INVESTIGATION_TOOLS, mcp_transport_status
from app.services.gemini_client import gemini_status
from app.services.schema_investigation import build_schema_investigation

logger = logging.getLogger(__name__)


def _transcript_step(step: str, message: str, *, tool: str | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build one transcript entry, stamped with the orchestrator and model that produced it."""
    payload: dict[str, Any] = {
        "step": step,
        "message": message,
        "ts": utc_now(),
        "orchestrator": "google_cloud_agent_builder" if settings.use_agent_builder else "gemini_orchestrator",
        "model": settings.gemini_model,
    }
    if tool:
        payload["tool"] = tool
    if extra:
        payload.update(extra)
    return payload


def _gemini_plan(
    contract: DataContract,
    validation_details: dict[str, Any],
    *,
    schema_investigation: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Ask Gemini for an investigation plan given the contract's failed checks; returns (plan, backend)."""
    failed = [c for c in validation_details.get("checks", []) if not c.get("passed")]
    failed_names = ", ".join(c.get("name", "?") for c in failed) or "unknown"
    return generate_investigation_plan(
        contract.contract_id,
        contract.fivetran_connector_id,
        failed_names,
        schema_investigation=schema_investigation,
    )


def _try_adk_run(contract: DataContract, validation_details: dict[str, Any]) -> dict[str, Any] | None:
    """Attempt the managed ADK agent turn when enabled and available.

    Returns the ADK result, ``None`` to fall back to the deterministic loop, or an ``{"error": ...}``
    dict. Honours ``require_agent_builder`` (re-raises instead of silently falling back).
    """
    if not settings.use_agent_builder:
        return None
    try:
        from agent_builder.mcp_config import adk_available
        from agent_builder.agent import run_guardian_turn

        if not adk_available():
            if settings.require_agent_builder:
                raise ImportError("google-adk not installed; pip install google-adk")
            return None

        from agent_builder.gemini_config import adk_gemini_ready
        from app.services.gemini_client import resolve_backend

        if (resolve_backend() == "none" or not adk_gemini_ready()) and not settings.require_agent_builder:
            return None

        return run_guardian_turn(contract, validation_details)
    except ImportError:
        if settings.require_agent_builder:
            raise
        return None
    except Exception as exc:  # noqa: BLE001
        if settings.require_agent_builder:
            raise
        return {"error": str(exc)[:300]}


def run_agent_investigation(
    contract: DataContract,
    validation_details: dict[str, Any],
    *,
    validation_passed: bool,
) -> dict[str, Any]:
    """
    Execute the full multi-step agent workflow for a contract validation outcome.
    Returns transcript steps, evidence bundles, RCA, ranked remediations, and fingerprint.
    """
    transcript: list[dict[str, Any]] = []

    if validation_passed:
        transcript.append(
            _transcript_step("DONE", f"Contract {contract.contract_id} passed — no incident opened.")
        )
        return {
            "transcript": transcript,
            "evidence_bundles": [],
            "root_cause": None,
            "confidence": None,
            "stakeholder_summary": None,
            "severity": "low",
            "ranked_remediations": [],
            "action_fingerprint": None,
            "orchestrator": settings.agent_name,
        }

    failed_checks = failed_check_names(validation_details)
    connector_context = get_connector_context(contract.fivetran_connector_id)

    adk_result = _try_adk_run(contract, validation_details)
    if adk_result and adk_result.get("transcript"):
        return adk_result
    if adk_result and adk_result.get("error"):
        logger.warning("ADK agent run failed; falling back to deterministic loop: %s", adk_result["error"])

    # Step 1 — PLAN (connector from FIVETRAN_CONNECTION_ID / terraform.tfvars)
    pre_plan_schema = {
        "connector": connector_context,
        "table": contract.bq_table,
        "bq_table_fqn": f"{contract.bq_project}.{contract.bq_dataset}.{contract.bq_table}",
        "required_columns": (
            list(contract.schema_block.required_columns)
            if contract.schema_block and contract.schema_block.required_columns
            else []
        ),
    }
    plan, gemini_backend = _gemini_plan(
        contract, validation_details, schema_investigation=pre_plan_schema
    )
    transcript.append(
        _transcript_step(
            "PLAN",
            plan,
            extra={
                "agent_builder": settings.use_agent_builder,
                "gemini_backend": gemini_backend,
                "connector_context": connector_context,
            },
        )
    )

    # Step 2 — Fivetran MCP tools, grounded in the actual failing checks
    mcp_result = fetch_fivetran_mcp_evidence(
        contract.fivetran_connector_id,
        drift_mode=True,
        failed_checks=failed_checks,
        tables=[contract.bq_table],
    )
    bundles: list[EvidenceBundlePayload] = [
        EvidenceBundlePayload.model_validate(b) for b in mcp_result.get("bundles", [])
    ]
    for tool in MCP_INVESTIGATION_TOOLS:
        matching = [b for b in bundles if b.tool_name == tool]
        if matching:
            mode = matching[0].data.get("mcp_mode", "unknown")
            errored = "error" in mode
            message = (
                f"Fivetran MCP → {tool}: not available for this connector — continuing with other tools"
                if errored
                else f"Fivetran MCP → {tool} (bundle {matching[0].bundle_id})"
            )
            transcript.append(
                _transcript_step(
                    "TOOL",
                    message,
                    tool=f"fivetran_mcp.{tool}",
                    extra={
                        "bundle_id": matching[0].bundle_id,
                        "source": "fivetran_mcp",
                        "status": "degraded" if errored else "ok",
                        "mcp_protocol": "Model Context Protocol",
                        "mcp_transport": mode,
                    },
                )
            )

    schema_investigation = build_schema_investigation(contract, validation_details, bundles)
    transcript.append(
        _transcript_step(
            "ANALYZE",
            (
                f"Schema cross-check for `{contract.bq_table}`: "
                f"{len(schema_investigation.get('missing_in_bigquery') or [])} missing in BigQuery, "
                f"{len(schema_investigation.get('missing_in_fivetran_schema') or [])} missing in Fivetran schema."
            ),
            extra={"schema_investigation": schema_investigation},
        )
    )

    # Step 3 — Warehouse validation tool
    val_snapshot = validate_data_contract(contract.contract_id)
    transcript.append(
        _transcript_step(
            "TOOL",
            "warehouse.validate_contract → checks attached to incident",
            tool="guardian.validate_data_contract",
            extra={"passed": val_snapshot.get("passed"), "check_count": len(validation_details.get("checks", []))},
        )
    )

    # Step 4 — SYNTH (Gemini RCA grounded in MCP evidence)
    root, confidence, summary = generate_rca_and_root_cause(contract.contract_id, validation_details, bundles)
    transcript.append(
        _transcript_step(
            "SYNTH",
            f"Evidence-grounded RCA (confidence {confidence:.0%}): {root[:200]}",
            extra={"confidence": confidence, "stakeholder_summary": summary},
        )
    )

    # Step 5 — PROPOSE ranked remediations (ARP), tailored to the failing check types
    ranked_objs = build_ranked_remediations(
        root,
        failed_checks=failed_checks,
        validation_details=validation_details,
        evidence_bundles=bundles,
    )
    ranked = [r.model_dump() for r in ranked_objs]
    transcript.append(
        _transcript_step(
            "PROPOSE",
            f"ARP ranked {len(ranked)} remediations — top: {ranked_objs[0].title if ranked_objs else 'none'}",
            extra={"remediations": ranked},
        )
    )

    # Step 6 — AWAIT human approval (HITL)
    transcript.append(
        _transcript_step(
            "AWAIT",
            "Human approval required before Slack/MR/sync side effects (human-in-the-loop gate)",
            extra={"risk_classes": [r["risk_class"] for r in ranked]},
        )
    )

    severity = classify_incident_severity(validation_details)["severity"]
    proposal = {"remediations": ranked, "contract_id": contract.contract_id}
    fingerprint = fingerprint_from_payload(proposal)

    return {
        "transcript": transcript,
        "evidence_bundles": bundles,
        "connector_context": connector_context,
        "schema_investigation": schema_investigation,
        "root_cause": root,
        "confidence": confidence,
        "stakeholder_summary": summary,
        "severity": severity,
        "ranked_remediations": ranked,
        "action_fingerprint": fingerprint,
        "orchestrator": settings.agent_name,
        "platform": {
            "agent_builder": settings.use_agent_builder,
            **gemini_status(),
            "fivetran_mcp_mode": "live" if settings.use_real_fivetran else "mock",
            "bigquery_mode": "live" if settings.use_live_bigquery else "mock",
        },
    }


def platform_status() -> dict[str, Any]:
    """Report integration status plus live workflow counters for judges."""
    from datetime import datetime, timezone

    from app.services.agent_response import AGENT_DISCLAIMER, CAPABILITY_PLATFORM

    adk_installed = False
    try:
        import google.adk  # noqa: F401

        adk_installed = True
    except ImportError:
        pass

    mcp_status = mcp_transport_status(lightweight=True)
    fivetran_source = "mock"
    if settings.use_real_fivetran and mcp_status.get("transport") == "stdio":
        fivetran_source = "mcp_stdio"
    elif settings.fivetran_credentials_configured and not settings.mock_fivetran_mcp:
        fivetran_source = "configured"

    from app.services.incident_service import count_open_incidents

    workflow = {
        "open_incidents": 0,
        "awaiting_approval": 0,
        "resolved": 0,
        "validation_runs": 0,
    }
    try:
        workflow = count_open_incidents()
    except Exception:  # noqa: BLE001
        pass

    return {
        "capability": CAPABILITY_PLATFORM,
        "disclaimer": AGENT_DISCLAIMER,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent": settings.agent_name,
        "agent_builder": {
            "enabled": settings.use_agent_builder,
            "adk_installed": adk_installed,
            "framework": "Google Cloud Agent Builder (ADK)",
        },
        "gemini": gemini_status(),
        "fivetran_mcp": {
            **mcp_status,
            "mock_mode": not settings.use_real_fivetran,
            "integration_source": fivetran_source,
            "credentials_configured": settings.fivetran_credentials_configured,
            "allow_writes": settings.fivetran_allow_writes,
            "connection_id_override": bool(settings.fivetran_connection_id),
            "configured_connection_ref": settings.fivetran_connection_id,
        },
        "bigquery": {
            "mock_mode": settings.mock_bigquery,
            "live_available": settings.use_live_bigquery,
            "project_id": settings.gcp_project_id,
        },
        "workflow": workflow,
    }

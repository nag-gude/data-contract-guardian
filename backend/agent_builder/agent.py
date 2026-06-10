"""
Google Cloud Agent Builder agent — Fivetran MCP via ADK MCPToolset.

Local ADK UI:
  cd backend && pip install -r requirements.txt
  PYTHONPATH=. adk web agent_builder

Production: FastAPI calls run_guardian_turn() when USE_AGENT_BUILDER=true.
"""

from __future__ import annotations

import json
from typing import Any

from google.genai import types

from agent_builder.gemini_config import adk_gemini_ready, build_adk_model, configure_adk_gemini_env
from agent_builder.mcp_config import adk_available, build_fivetran_mcp_toolset
from app.config import settings
from app.schemas import DataContract
from app.services.agent_rca import (
    build_ranked_remediations,
    fingerprint_from_payload,
    generate_investigation_plan,
    generate_rca_and_root_cause,
)
from app.services.agent_tools import classify_incident_severity, validate_data_contract
from app.services.fivetran_mcp import MCP_INVESTIGATION_TOOLS, fetch_investigation_evidence


def _step(step: str, message: str, **extra: Any) -> dict[str, Any]:
    """Build one ADK transcript entry tagged with orchestrator, model, and framework metadata."""
    from app.schemas import utc_now

    return {
        "step": step,
        "message": message,
        "ts": utc_now(),
        "orchestrator": "google_cloud_agent_builder",
        "model": settings.gemini_model,
        "framework": "google-adk",
        **extra,
    }


def _build_agent():
    """Construct the ADK ``Agent`` with Fivetran MCPToolset when live, else a validation-only tool."""
    from google.adk import Agent

    configure_adk_gemini_env()
    model = build_adk_model()

    if not settings.mock_fivetran_mcp and settings.fivetran_credentials_configured:
        tools: list[Any] = [build_fivetran_mcp_toolset(), validate_data_contract]
        instruction = (
            "You are Data Contract Guardian, a reliability agent for Fivetran → BigQuery pipelines. "
            "Use the Fivetran MCP tools (get_connection_details, get_connection_state, "
            "get_connection_schema_config) and validate_data_contract to investigate failures. "
            "Ground every conclusion in MCP tool output only."
        )
    else:
        tools = [validate_data_contract]
        instruction = (
            "You are Data Contract Guardian. Use validate_data_contract; "
            "Fivetran MCP runs in mock mode for this session."
        )

    return Agent(
        model=model,
        name=settings.agent_name,
        description="Fivetran MCP-grounded data contract reliability agent",
        instruction=instruction,
        tools=tools,
    )


def run_guardian_turn(contract: DataContract, validation_details: dict[str, Any]) -> dict[str, Any]:
    """Run investigation via ADK Agent + Fivetran MCPToolset."""
    if not adk_available():
        raise ImportError("google-adk is required; pip install google-adk")
    if not adk_gemini_ready():
        raise RuntimeError(
            "ADK Gemini auth not configured — set GCP_PROJECT_ID (Vertex) or GEMINI_API_KEY (AI Studio)."
        )

    from google.adk.runners import InMemoryRunner

    failed = [c for c in validation_details.get("checks", []) if not c.get("passed")]
    failed_names = [c.get("name") for c in failed]
    user_msg = (
        f"Contract {contract.contract_id} failed validation. "
        f"Fivetran connector id: {contract.fivetran_connector_id}. "
        f"Failed checks: {[c.get('name') for c in failed]}. "
        f"Call Fivetran MCP tools for connector {contract.fivetran_connector_id}, "
        "then validate_data_contract."
    )

    # PLAN — a Gemini-authored investigation plan (not just the user prompt), so the transcript
    # shows the model's reasoning.
    plan_text, gemini_backend = generate_investigation_plan(
        contract.contract_id,
        contract.fivetran_connector_id,
        ", ".join(str(n) for n in failed_names) or "unknown",
    )
    transcript: list[dict[str, Any]] = [
        _step(
            "PLAN",
            plan_text,
            gemini_backend=gemini_backend,
            mcp_transport="stdio",
            mcp_server="github.com/fivetran/fivetran-mcp",
        )
    ]

    agent = _build_agent()
    runner = InMemoryRunner(agent=agent, app_name=settings.agent_name)
    runner.session_service.create_session_sync(
        app_name=settings.agent_name,
        user_id="guardian",
        session_id=contract.contract_id,
    )
    message = types.Content(role="user", parts=[types.Part(text=user_msg)])

    for event in runner.run(
        user_id="guardian",
        session_id=contract.contract_id,
        new_message=message,
    ):
        payload: dict[str, Any] = {"framework": "google-adk"}
        if hasattr(event, "model_dump"):
            dumped = event.model_dump()
            payload.update(dumped)
            if dumped.get("error_code") or dumped.get("error_message"):
                err = dumped.get("error_message") or dumped.get("error_code")
                raise RuntimeError(f"ADK model error: {err}")
            if "content" in dumped:
                transcript.append(_step("ADK", json.dumps(dumped)[:600], **payload))
            elif dumped.get("type") == "tool_call" or "function_call" in str(dumped).lower():
                transcript.append(
                    _step(
                        "TOOL",
                        f"ADK MCP tool invocation: {json.dumps(dumped)[:400]}",
                        tool="fivetran_mcp.via_adk",
                        **payload,
                    )
                )
            else:
                transcript.append(_step("ADK", json.dumps(dumped, default=str)[:400], **payload))
        else:
            transcript.append(_step("ADK", str(event)[:400], **payload))

    # Persist evidence bundles via our MCP stdio layer (same server ADK used), grounded in failures
    bundles = fetch_investigation_evidence(
        contract.fivetran_connector_id, drift_mode=True, failed_checks=failed_names, tables=[contract.bq_table]
    )
    for b in bundles:
        mode = b.data.get("mcp_mode", "unknown")
        errored = "error" in mode
        msg = (
            f"Fivetran MCP → {b.tool_name}: not available for this connector — continuing with other tools"
            if errored
            else f"Fivetran MCP ({mode}) → {b.tool_name} bundle {b.bundle_id}"
        )
        transcript.append(
            _step(
                "TOOL",
                msg,
                tool=f"fivetran_mcp.{b.tool_name}",
                status="degraded" if errored else "ok",
                mcp_protocol="Model Context Protocol",
                mcp_transport="stdio",
            )
        )

    root, confidence, summary = generate_rca_and_root_cause(contract.contract_id, validation_details, bundles)
    ranked = [
        r.model_dump()
        for r in build_ranked_remediations(
            root,
            failed_checks=failed_names,
            validation_details=validation_details,
            evidence_bundles=bundles,
        )
    ]
    transcript.extend(
        [
            _step("SYNTH", root[:300], confidence=confidence, gemini_model=settings.gemini_model),
            _step("PROPOSE", f"Ranked {len(ranked)} remediations"),
            _step("AWAIT", "Human approval required (HITL gate)"),
        ]
    )

    return {
        "transcript": transcript,
        "evidence_bundles": bundles,
        "root_cause": root,
        "confidence": confidence,
        "stakeholder_summary": summary,
        "severity": classify_incident_severity(validation_details)["severity"],
        "ranked_remediations": ranked,
        "action_fingerprint": fingerprint_from_payload({"remediations": ranked, "contract_id": contract.contract_id}),
        "orchestrator": settings.agent_name,
        "platform": {
            "agent_builder": True,
            "framework": "google-adk",
            "mcp_toolset": "McpToolset → fivetran/fivetran-mcp",
        },
    }


# ADK CLI discovery (`adk web agent_builder`)
try:
    root_agent = _build_agent()
except Exception:  # noqa: BLE001
    root_agent = None

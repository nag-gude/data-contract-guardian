"""Agent API response helpers — capability tags, MCP trace, judge-friendly summaries."""

from __future__ import annotations

from typing import Any

from app.schemas import EvidenceBundlePayload

AGENT_DISCLAIMER = (
    "Read-only agent surface: investigation and remediation proposals only. "
    "Approve or reject remediations in the Data Contract Guardian UI — not via agent APIs."
)

CAPABILITY_INVESTIGATE = "investigate_only"
CAPABILITY_PIPELINE = "pipeline_orchestration"
CAPABILITY_PLATFORM = "platform_status"
CAPABILITY_MCP_DISCOVERY = "mcp_discovery"


# Approval/execute fields belong on incidents API — not on agent investigation routes.
_FORBIDDEN_AGENT_BODY_KEYS = frozenset(
    {
        "approve",
        "approval_id",
        "approver_id",
        "action_fingerprint",
        "idempotency_key",
        "execute",
        "execute_remediation",
    }
)


def reject_execution_shaped_body(body: dict[str, Any] | None) -> str | None:
    """Return an error message if the body looks like an execution/approval request."""
    if not body:
        return None
    for key in body:
        if key.lower() in _FORBIDDEN_AGENT_BODY_KEYS:
            return (
                f"Field '{key}' is not allowed on read-only agent endpoints. "
                "Use POST /api/incidents/approve-remediation or the UI approval panel."
            )
    return None


def build_mcp_trace(bundles: list[EvidenceBundlePayload] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact per-tool trace for judges and chat agents — proves MCP was invoked."""
    trace: list[dict[str, Any]] = []
    for raw in bundles:
        if isinstance(raw, EvidenceBundlePayload):
            b = raw
            data = b.data
            tool = b.tool_name
            connector = b.connector_id
        else:
            data = raw.get("data") or raw
            tool = raw.get("tool_name") or data.get("tool_name") or "unknown"
            connector = raw.get("connector_id")
        is_error = bool(data.get("is_error") or data.get("error"))
        mode = data.get("mcp_mode", "unknown")
        summary = _bundle_summary(tool, data, is_error)
        trace.append(
            {
                "tool": tool,
                "ok": not is_error,
                "mcp_mode": mode,
                "connector_id": connector,
                "resolved_connection_id": data.get("resolved_connection_id"),
                "summary": summary,
            }
        )
    return trace


def _bundle_summary(tool: str, data: dict[str, Any], is_error: bool) -> str:
    if is_error:
        err = data.get("error") or data.get("text") or "tool error"
        return str(err)[:200]
    resp = data.get("fivetran_response")
    if isinstance(resp, dict):
        if tool == "get_connection_details":
            inner = resp.get("data", resp) if isinstance(resp.get("data"), dict) else resp
            status = inner.get("status", {}) if isinstance(inner.get("status"), dict) else {}
            sync = status.get("sync_state")
            paused = inner.get("paused")
            succeeded = inner.get("succeeded_at")
            parts = [p for p in (f"sync_state={sync}" if sync else None, f"paused={paused}" if paused is not None else None, f"succeeded_at={succeeded}" if succeeded else None) if p]
            return ", ".join(parts) if parts else "connection details retrieved"
        if tool == "get_connection_state":
            inner = resp.get("data", resp)
            sync = inner.get("sync_state", "unknown")
            enriched = inner.get("enriched_from")
            paused = inner.get("paused")
            parts = [f"sync_state={sync}"]
            if paused is not None:
                parts.append(f"paused={paused}")
            if enriched:
                parts.append(f"from {enriched}")
            return ", ".join(parts)
        if tool == "get_connection_schema_config":
            inner = resp.get("data", resp)
            schemas = inner.get("schemas") or {}
            return f"schemas={len(schemas)} configured"
        if tool == "get_account_info":
            inner = resp.get("data", resp)
            count = inner.get("connection_count") or inner.get("id")
            return f"account info retrieved (connections={count})"
        if tool == "list_connections":
            inner = resp.get("data", resp)
            items = inner.get("items") if isinstance(inner, dict) else None
            n = len(items) if isinstance(items, list) else "?"
            return f"{n} connection(s) listed"
        if tool == "list_destinations":
            inner = resp.get("data", resp)
            items = inner.get("items") if isinstance(inner, dict) else None
            n = len(items) if isinstance(items, list) else "?"
            return f"{n} destination(s) listed"
    if tool == "get_account_info" and data.get("connection_count") is not None:
        return f"account active — {data['connection_count']} connection(s)"
    if tool == "list_connections" and isinstance(data.get("data"), dict):
        items = data["data"].get("items") or []
        return f"{len(items)} connection(s) listed"
    if tool == "list_destinations" and isinstance(data.get("items"), list):
        return f"{len(data['items'])} destination(s) listed"
    if data.get("sync_status"):
        return f"sync_status={data['sync_status']}"
    if data.get("recent_errors"):
        return f"errors={len(data['recent_errors'])}"
    return "ok"


def build_summary_for_agent(
    *,
    contract_id: str,
    validation_passed: bool,
    validation_details: dict[str, Any],
    severity: str | None,
    incident_id: str | None,
    mcp_trace: list[dict[str, Any]],
    ranked_remediations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Authoritative fields for LLM narration — cite these instead of inventing counts."""
    failed = [c.get("name") for c in validation_details.get("checks", []) if not c.get("passed")]
    mcp_ok = sum(1 for t in mcp_trace if t.get("ok"))
    instruction = (
        "Contract passed — no incident required."
        if validation_passed
        else (
            f"Open incident {incident_id} in the UI for human approval of ranked remediations."
            if incident_id
            else "Validation failed — call investigate with open_incident via UI workflow, not agent API."
        )
    )
    return {
        "contract_id": contract_id,
        "validation_passed": validation_passed,
        "failed_checks": failed,
        "failed_check_count": len(failed),
        "warehouse_source": validation_details.get("warehouse_source"),
        "severity": severity,
        "incident_id": incident_id,
        "mcp_tools_ok": mcp_ok,
        "mcp_tools_total": len(mcp_trace),
        "remediation_count": len(ranked_remediations or []),
        "instruction": instruction,
    }


def enrich_investigation_result(result: dict[str, Any], *, incident_id: str | None = None) -> dict[str, Any]:
    """Attach capability, disclaimer, mcp_trace, and summary_for_agent to an investigation dict."""
    bundles = result.get("evidence_bundles") or []
    trace = build_mcp_trace(bundles)
    contract_id = result.get("contract_id", "")
    validation_passed = result.get("validation_passed", True)
    validation_details = result.get("validation_details") or {}
    summary = build_summary_for_agent(
        contract_id=contract_id,
        validation_passed=validation_passed,
        validation_details=validation_details,
        severity=result.get("severity"),
        incident_id=incident_id,
        mcp_trace=trace,
        ranked_remediations=result.get("ranked_remediations"),
    )
    return {
        **result,
        "capability": CAPABILITY_INVESTIGATE,
        "disclaimer": AGENT_DISCLAIMER,
        "mcp_trace": trace,
        "summary_for_agent": summary,
    }

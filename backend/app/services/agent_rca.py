"""Gemini-powered reasoning: investigation plans, root-cause analysis, and remediations.

Every Gemini call here is **evidence-grounded** — the model is asked to reason only over the
persisted validation details and Fivetran MCP evidence bundles — and every call degrades
gracefully to a deterministic template when no Gemini backend is configured, so the agent loop
always produces a usable result. Remediations and the approval fingerprint are deterministic by
design (the fingerprint must be stable for the HITL gate to validate it).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.schemas import EvidenceBundlePayload, RemediationOption, utc_now
from app.services.gemini_client import generate_json, generate_text


def fingerprint_from_payload(payload: dict[str, Any]) -> str:
    """Stable SHA-256 over a canonical JSON payload — the action fingerprint for HITL approval."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def _connector_state_from_evidence(
    evidence_bundles: list[EvidenceBundlePayload] | list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Extract paused/sync_state/succeeded_at from Fivetran MCP investigation bundles."""
    state: dict[str, Any] = {}
    for raw in evidence_bundles or []:
        if isinstance(raw, EvidenceBundlePayload):
            tool = raw.tool_name
            data = raw.data
        else:
            tool = raw.get("tool_name") or (raw.get("data") or {}).get("tool_name")
            data = raw.get("data") or raw
        if tool not in {"get_connection_details", "get_connection_state"}:
            continue
        resp = data.get("fivetran_response") if isinstance(data, dict) else None
        if not isinstance(resp, dict):
            continue
        inner = resp.get("data", resp) if isinstance(resp.get("data"), dict) else resp
        if isinstance(inner, dict):
            status = inner.get("status") if isinstance(inner.get("status"), dict) else {}
            state.setdefault("sync_state", status.get("sync_state") or inner.get("sync_state"))
            state.setdefault("update_state", status.get("update_state") or inner.get("update_state"))
            state.setdefault("paused", inner.get("paused"))
            state.setdefault("succeeded_at", inner.get("succeeded_at"))
            state.setdefault("connection_id", inner.get("connection_id") or inner.get("id"))
    return state


def _freshness_remediation(
    *,
    freshness: dict[str, Any],
    connector_state: dict[str, Any],
) -> RemediationOption:
    age = freshness.get("age_minutes")
    cap = freshness.get("max_delay_minutes")
    detail = f" ({age:.0f}min > {cap}min cap)" if isinstance(age, (int, float)) and cap else ""

    paused = connector_state.get("paused") is True
    sync_state = str(connector_state.get("sync_state") or "").lower()
    succeeded_at = connector_state.get("succeeded_at")

    if paused or sync_state == "paused":
        return RemediationOption(
            rank=0,
            title="Resume paused Fivetran sync and trigger a catch-up run",
            risk_class="R4",
            rationale=(
                f"Fivetran MCP reports connector paused or sync_state=paused{detail}; "
                "resume sync and re-verify BigQuery freshness."
            ),
        )

    sync_note = f" last_sync={succeeded_at}" if succeeded_at else ""
    return RemediationOption(
        rank=0,
        title="Trigger manual Fivetran sync and investigate BigQuery ingestion lag",
        risk_class="R3",
        rationale=(
            f"Connector is active (sync_state={sync_state or 'scheduled'}, not paused) but "
            f"BigQuery table metadata is stale{detail}.{sync_note} "
            "Review Fivetran sync logs and compare succeeded_at vs BigQuery last_modified."
        ),
    )


def build_ranked_remediations(
    violation_summary: str,
    failed_checks: list[str] | None = None,
    validation_details: dict[str, Any] | None = None,
    evidence_bundles: list[EvidenceBundlePayload] | list[dict[str, Any]] | None = None,
) -> list[RemediationOption]:
    """
    ARP-style ranked remediation list, tailored to the failing check types so the agent's
    proposal is specific to the incident rather than a fixed boilerplate set.

    • schema/type drift → SAFE_CAST shim MR per failed column (from validation checks[])
    • freshness/stale   → paused sync resume OR ingestion-lag investigation (from MCP evidence)
    Falls back to a generic coordination plan when the failure type is unknown.
    """
    failed = failed_checks or []
    schema_drift = any(c.startswith("schema") for c in failed)
    stale = any(c == "freshness" for c in failed)
    checks_by_name = {
        c.get("name"): c for c in (validation_details or {}).get("checks", []) if c.get("name")
    }

    issue_option = RemediationOption(
        rank=0,
        title="Create GitHub issue with evidence bundle links",
        risk_class="R2",
        rationale="Coordinates owners without mutating the warehouse or connector.",
    )

    options: list[RemediationOption] = []

    if schema_drift:
        type_failures = [
            (name, checks_by_name.get(name, {}))
            for name in failed
            if name.startswith("schema_type_")
        ]
        if type_failures:
            for check_name, check in type_failures:
                col = check_name[len("schema_type_") :]
                expected = check.get("expected", "expected type")
                actual = check.get("actual", "observed type")
                options.append(
                    RemediationOption(
                        rank=0,
                        title=f"Open draft MR: SAFE_CAST `{col}` to {expected} (currently {actual}) in dbt model",
                        risk_class="R3",
                        rationale=(
                            f"Directly resolves the {actual}→{expected} drift on `{col}` "
                            "detected by the contract validation check; reversible via MR revert."
                        ),
                    )
                )
        else:
            missing_check = checks_by_name.get("schema_required_columns", {})
            missing_cols = missing_check.get("missing") or []
            if missing_cols:
                cols = ", ".join(f"`{c}`" for c in missing_cols)
                options.append(
                    RemediationOption(
                        rank=0,
                        title=f"Restore missing columns {cols} in source or Fivetran schema config",
                        risk_class="R3",
                        rationale="Required columns absent from BigQuery — re-enable in Fivetran or fix upstream Airtable schema.",
                    )
                )
            else:
                options.append(
                    RemediationOption(
                        rank=0,
                        title="Review Fivetran schema config and dbt models for schema drift",
                        risk_class="R3",
                        rationale="Schema checks failed — align connector column types with contract expectations.",
                    )
                )

    if stale:
        connector_state = _connector_state_from_evidence(evidence_bundles)
        options.append(
            _freshness_remediation(
                freshness=checks_by_name.get("freshness", {}),
                connector_state=connector_state,
            )
        )

    options.append(issue_option)

    if not schema_drift and not stale:
        options.append(
            RemediationOption(
                rank=0,
                title="Pause non-critical connector sync window (advisory)",
                risk_class="R4",
                rationale="Stops bleed only if ops policy allows; requires strong approval.",
            )
        )

    for i, opt in enumerate(options, start=1):
        opt.rank = i
    return options


def generate_rca_and_root_cause(
    contract_id: str,
    validation_details: dict[str, Any],
    evidence: list[EvidenceBundlePayload],
) -> tuple[str, float, str]:
    """Returns (root_cause, confidence 0-1, stakeholder_summary)."""
    bundles_txt = json.dumps([e.model_dump() for e in evidence], indent=2)[:8000]
    checks_txt = json.dumps(validation_details, indent=2)[:4000]

    prompt = f"""You are a data reliability incident assistant for Fivetran → BigQuery pipelines.
Ground every claim ONLY in the evidence JSON below — do not invent facts.

Contract: {contract_id}
Validation details:
{checks_txt}

Fivetran MCP evidence bundles:
{bundles_txt}

Respond in JSON only with keys: root_cause (one sentence), confidence (0.0-1.0), stakeholder_summary (2 short sentences for Slack).
"""
    data, backend = generate_json(prompt)
    if data and backend != "none":
        root = str(data.get("root_cause", ""))[:500]
        confidence = float(data.get("confidence", 0.7))
        summary = str(data.get("stakeholder_summary", "")).strip()[:800]
        if not summary:
            summary = _fallback_stakeholder_summary(contract_id, validation_details)
        if root:
            return root, confidence, summary

    failed = [c for c in validation_details.get("checks", []) if not c.get("passed")]
    root = f"Contract {contract_id} failed checks: {', '.join(c.get('name','?') for c in failed)}"
    return root, 0.75 if failed else 0.5, _fallback_stakeholder_summary(contract_id, validation_details)


def _fallback_stakeholder_summary(contract_id: str, validation_details: dict[str, Any]) -> str:
    """Deterministic Slack-ready summary when Gemini returns an empty stakeholder_summary."""
    failed = [c.get("name", "?") for c in validation_details.get("checks", []) if not c.get("passed")]
    checks = ", ".join(failed) if failed else "unknown checks"
    return (
        f"Data contract alert for `{contract_id}`: failed {checks}. "
        "Engineering is investigating with live Fivetran MCP evidence attached."
    )


def generate_investigation_plan(
    contract_id: str,
    connector_id: str,
    failed_names: str,
    *,
    schema_investigation: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Gemini-generated plan. Returns (plan_text, gemini_backend)."""
    connector_ctx = (schema_investigation or {}).get("connector") or {}
    resolved = connector_ctx.get("resolved_connection_id") or connector_id
    configured = connector_ctx.get("configured_connection_ref")
    table = (schema_investigation or {}).get("table", "")
    required = (schema_investigation or {}).get("required_columns") or []
    bq_fqn = (schema_investigation or {}).get("bq_table_fqn", "")

    prompt = f"""You are a data reliability agent for Fivetran → BigQuery pipelines.
Contract: {contract_id}
Fivetran connector (resolved): {resolved}
Configured ref (terraform.tfvars / FIVETRAN_CONNECTION_ID): {configured or "auto"}
BigQuery table: {bq_fqn or table}
Required columns: {", ".join(required) if required else "unknown"}
Failed checks: {failed_names}

Write a 3-sentence investigation plan that:
1) calls get_connection_schema_config and reviews the Fivetran UI Schema tab + sync logs,
2) verifies the source system schema for required columns,
3) compares the BigQuery destination table for discrepancies.
Respond with plain text only."""
    text, backend = generate_text(prompt)
    if text:
        return text[:800], backend

    env_note = f" (from FIVETRAN_CONNECTION_ID={configured})" if configured else ""
    return (
        f"Plan for {contract_id}: use Fivetran connector `{resolved}`{env_note}; "
        f"call get_connection_details, get_connection_state, and get_connection_schema_config for "
        f"table `{table}`; inspect the Fivetran UI Schema tab and sync logs; verify source columns "
        f"{', '.join(required) if required else '(see contract)'}; "
        f"compare BigQuery `{bq_fqn}` against contract rules. Failed: {failed_names}.",
        "none",
    )

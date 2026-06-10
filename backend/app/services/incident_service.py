"""Incident lifecycle and human-in-the-loop remediation.

Owns the full incident record in SQLite: creating one from a failed validation (persisting the
agent transcript, evidence bundles, RCA, and ranked remediations), reading it back for the API,
and the approval flow. Approval is fingerprint-gated and idempotent; on approval it records the
decision, fires optional side effects (Slack), then **re-validates** the contract to either
resolve the incident or surface ``verify_failed`` — closing the agent's loop.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.config import settings
from app.db import get_conn
from app.schemas import (
    ApproveBody,
    DataContract,
    IncidentDetail,
    IncidentPublic,
    RemediationOption,
    utc_now,
)
from app.services.agent_orchestrator import run_agent_investigation
from app.services.agent_rca import fingerprint_from_payload
from app.services.remediation_executor import execute_top_remediation, verify_with_retry


def _incident_from_row(row: dict[str, Any]) -> IncidentPublic:
    """Map a raw ``incidents`` table row into an ``IncidentPublic`` model."""
    ranked_raw = json.loads(row["ranked_remediations"] or "[]")
    ranked = [RemediationOption(**r) for r in ranked_raw]
    return IncidentPublic(
        id=row["id"],
        contract_id=row["contract_id"],
        fivetran_connector_id=row["fivetran_connector_id"],
        severity=row["severity"],
        status=row["status"],
        root_cause=row["root_cause"],
        confidence=row["confidence"],
        remediation_status=row["remediation_status"],
        evidence_bundle_ids=json.loads(row["evidence_bundle_ids"] or "[]"),
        action_fingerprint=row["action_fingerprint"],
        ranked_remediations=ranked,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


OPEN_INCIDENT_STATUSES = ("awaiting_approval", "executing", "verify_failed")
_OPEN_STATUSES = OPEN_INCIDENT_STATUSES


def find_open_incident(contract_id: str) -> str | None:
    """Return the id of the newest open incident for a contract, if any."""
    placeholders = ",".join("?" for _ in OPEN_INCIDENT_STATUSES)
    with get_conn() as conn:
        row = conn.execute(
            f"""
            SELECT id FROM incidents
            WHERE contract_id = ? AND status IN ({placeholders})
            ORDER BY datetime(created_at) DESC
            LIMIT 1
            """,
            (contract_id, *OPEN_INCIDENT_STATUSES),
        ).fetchone()
    return row["id"] if row else None


def prune_duplicate_incidents() -> dict[str, Any]:
    """Cancel duplicate open incidents, keeping the newest per contract_id."""
    placeholders = ",".join("?" for _ in OPEN_INCIDENT_STATUSES)
    cancelled: list[str] = []
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT id, contract_id, created_at FROM incidents
            WHERE status IN ({placeholders})
            ORDER BY contract_id, datetime(created_at) DESC
            """,
            OPEN_INCIDENT_STATUSES,
        ).fetchall()
        seen: set[str] = set()
        now = utc_now()
        for row in rows:
            cid = row["contract_id"]
            if cid in seen:
                conn.execute(
                    "UPDATE incidents SET status = ?, updated_at = ? WHERE id = ?",
                    ("cancelled", now, row["id"]),
                )
                cancelled.append(row["id"])
            else:
                seen.add(cid)
    return {"ok": True, "cancelled": cancelled, "count": len(cancelled)}


def list_incidents(*, open_only: bool = False) -> list[IncidentPublic]:
    """Return up to 100 most-recent incidents as summary models."""
    with get_conn() as conn:
        if open_only:
            placeholders = ",".join("?" for _ in OPEN_INCIDENT_STATUSES)
            rows = conn.execute(
                f"""
                SELECT * FROM incidents
                WHERE status IN ({placeholders})
                ORDER BY datetime(created_at) DESC
                LIMIT 100
                """,
                OPEN_INCIDENT_STATUSES,
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM incidents ORDER BY datetime(created_at) DESC LIMIT 100"
            ).fetchall()
    return [_incident_from_row(dict(r)) for r in rows]


def count_open_incidents() -> dict[str, int]:
    """Workflow counters — same definition as list_incidents(open_only=True)."""
    placeholders = ",".join("?" for _ in OPEN_INCIDENT_STATUSES)
    with get_conn() as conn:
        open_total = conn.execute(
            f"SELECT COUNT(*) FROM incidents WHERE status IN ({placeholders})",
            OPEN_INCIDENT_STATUSES,
        ).fetchone()[0]
        awaiting = conn.execute(
            "SELECT COUNT(*) FROM incidents WHERE status = 'awaiting_approval'"
        ).fetchone()[0]
        resolved = conn.execute(
            "SELECT COUNT(*) FROM incidents WHERE status = 'resolved'"
        ).fetchone()[0]
        validation_runs = conn.execute("SELECT COUNT(*) FROM validation_runs").fetchone()[0]
    return {
        "open_incidents": open_total,
        "awaiting_approval": awaiting,
        "resolved": resolved,
        "validation_runs": validation_runs,
    }


def get_incident(incident_id: str) -> IncidentDetail | None:
    """Return the full incident (summary + agent transcript events + evidence), or ``None``."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if not row:
            return None
        ev_rows = conn.execute(
            "SELECT * FROM evidence_bundles WHERE incident_id = ? ORDER BY datetime(created_at)",
            (incident_id,),
        ).fetchall()
        ev = [json.loads(r["payload"]) for r in ev_rows]
        events = conn.execute(
            "SELECT event_type as type, payload, created_at FROM incident_events WHERE incident_id = ? ORDER BY id",
            (incident_id,),
        ).fetchall()
        evts = []
        for r in events:
            p = json.loads(r["payload"]) if r["payload"] else {}
            evts.append({"type": r["type"], **p, "created_at": r["created_at"]})
    base = _incident_from_row(dict(row))
    return IncidentDetail(**base.model_dump(), events=evts, evidence=ev)


def create_incident_for_failure(
    contract: DataContract,
    validation_passed: bool,
    details: dict[str, Any],
    investigation: dict[str, Any] | None = None,
) -> IncidentPublic | None:
    """Open and persist an incident for a failed validation.

    Runs the agent investigation if one wasn't passed in, then stores the incident, its evidence
    bundles, and the agent transcript. Returns ``None`` when validation actually passed (no-op).
    """
    if validation_passed:
        return None

    if investigation is None:
        investigation = run_agent_investigation(contract, details, validation_passed=False)

    existing_id = find_open_incident(contract.contract_id)
    if existing_id:
        return get_incident(existing_id)

    iid = f"inc-{uuid.uuid4().hex[:12]}"
    now = utc_now()
    bundles = investigation["evidence_bundles"]
    bundle_ids = [b.bundle_id for b in bundles]

    with get_conn() as conn:
        for ev in bundles:
            conn.execute(
                "INSERT INTO evidence_bundles (id, incident_id, payload, created_at) VALUES (?,?,?,?)",
                (ev.bundle_id, iid, ev.model_dump_json(), now),
            )

        ranked = investigation["ranked_remediations"]
        fp = investigation["action_fingerprint"] or fingerprint_from_payload(
            {"remediations": ranked, "contract_id": contract.contract_id}
        )

        conn.execute(
            """
            INSERT INTO incidents (
                id, contract_id, fivetran_connector_id, severity, status, root_cause, confidence,
                remediation_status, evidence_bundle_ids, action_fingerprint, ranked_remediations,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                iid,
                contract.contract_id,
                contract.fivetran_connector_id,
                investigation["severity"],
                "awaiting_approval",
                investigation["root_cause"],
                investigation["confidence"],
                "pending",
                json.dumps(bundle_ids),
                fp,
                json.dumps(ranked),
                now,
                now,
            ),
        )
        for step in investigation["transcript"]:
            conn.execute(
                "INSERT INTO incident_events (incident_id, event_type, payload, created_at) VALUES (?,?,?,?)",
                (iid, "agent_step", json.dumps(step), step["ts"]),
            )

    return get_incident(iid)


def append_event(incident_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """Append a timestamped event (approval, execution, verification, …) to an incident."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO incident_events (incident_id, event_type, payload, created_at) VALUES (?,?,?,?)",
            (incident_id, event_type, json.dumps(payload), utc_now()),
        )


def approve_remediation(body: ApproveBody) -> dict[str, Any]:
    """Process a HITL approve/reject decision for an incident's proposed remediation.

    Idempotent on ``idempotency_key`` and gated on ``action_fingerprint`` matching the incident.
    On rejection the incident is cancelled. On approval it transitions to executing, optionally
    posts to Slack, then re-validates the contract — resolving the incident on success or marking
    ``verify_failed`` (and re-opening for approval) on failure. Returns a small status dict.
    """
    with get_conn() as conn:
        if body.idempotency_key:
            existing = conn.execute(
                "SELECT id FROM approvals WHERE incident_id = ? AND idempotency_key = ?",
                (body.incident_id, body.idempotency_key),
            ).fetchone()
            if existing:
                return {"ok": True, "duplicate": True}

        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (body.incident_id,)).fetchone()
        if not row:
            return {"ok": False, "error": "incident not found"}
        inc = dict(row)
        if body.action_fingerprint != inc["action_fingerprint"]:
            return {"ok": False, "error": "fingerprint mismatch"}

        if not body.approve:
            conn.execute(
                "UPDATE incidents SET status = ?, updated_at = ? WHERE id = ?",
                ("cancelled", utc_now(), body.incident_id),
            )
            conn.execute(
                "INSERT INTO approvals (incident_id, action_fingerprint, approver_id, approved, idempotency_key, created_at) VALUES (?,?,?,?,?,?)",
                (body.incident_id, body.action_fingerprint, body.approver_id, 0, body.idempotency_key, utc_now()),
            )
            append_event(body.incident_id, "approval", {"approved": False, "approver": body.approver_id})
            return {"ok": True, "status": "cancelled"}

        conn.execute(
            "UPDATE incidents SET status = ?, remediation_status = ?, updated_at = ? WHERE id = ?",
            ("executing", "in_progress", utc_now(), body.incident_id),
        )
        conn.execute(
            "INSERT INTO approvals (incident_id, action_fingerprint, approver_id, approved, idempotency_key, created_at) VALUES (?,?,?,?,?,?)",
            (body.incident_id, body.action_fingerprint, body.approver_id, 1, body.idempotency_key, utc_now()),
        )

    ranked_raw = json.loads(inc["ranked_remediations"] or "[]")
    ranked = [RemediationOption(**r) for r in ranked_raw]

    from app.services.contracts_loader import get_contract

    contract = get_contract(inc["contract_id"])
    if not contract:
        return {"ok": False, "error": "contract missing"}

    execution = execute_top_remediation(
        contract,
        ranked,
        connector_ref=inc.get("fivetran_connector_id"),
    )
    append_event(
        body.incident_id,
        "execution",
        {
            "message": "Remediation approved — executing top-ranked action",
            "approver": body.approver_id,
            "remediation": ranked[0].title if ranked else None,
            **execution,
        },
    )

    if settings.slack_webhook_url:
        try:
            import httpx

            httpx.post(
                settings.slack_webhook_url,
                json={"text": f"Data Contract Guardian: remediation approved for `{inc['contract_id']}` by {body.approver_id}."},
                timeout=10.0,
            )
        except Exception:  # noqa: BLE001
            pass

    passed, details, verify_attempts = verify_with_retry(
        contract,
        await_verification=execution.get("await_verification", False),
    )
    now = utc_now()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO validation_runs (id, contract_id, passed, details, created_at) VALUES (?,?,?,?,?)",
            (f"vr-{uuid.uuid4().hex[:10]}", contract.contract_id, int(passed), json.dumps(details), now),
        )
        if passed:
            conn.execute(
                "UPDATE incidents SET status = ?, remediation_status = ?, updated_at = ? WHERE id = ?",
                ("resolved", "verified", now, body.incident_id),
            )
            conn.execute(
                "INSERT INTO resolution_memory (id, incident_id, remediation_signature, outcome, time_to_verify_ms, approver_id, closed_at) VALUES (?,?,?,?,?,?,?)",
                (
                    f"res-{uuid.uuid4().hex[:10]}",
                    body.incident_id,
                    body.action_fingerprint,
                    "success",
                    0,
                    body.approver_id,
                    now,
                ),
            )
        else:
            conn.execute(
                "UPDATE incidents SET status = ?, remediation_status = ?, updated_at = ? WHERE id = ?",
                ("awaiting_approval", "verify_failed", now, body.incident_id),
            )

    append_event(
        body.incident_id,
        "verification",
        {"passed": passed, "details": details, "attempts": verify_attempts},
    )
    failed_checks = [c.get("name") for c in details.get("checks", []) if not c.get("passed")]
    return {
        "ok": True,
        "verification_passed": passed,
        "details": details,
        "execution": execution,
        "failed_checks": failed_checks,
        "verify_attempts": verify_attempts,
    }

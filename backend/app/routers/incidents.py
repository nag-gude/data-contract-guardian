"""Incidents router — list and inspect incidents, and approve/reject remediations.

The approval endpoint is the human-in-the-loop gate: it verifies the action fingerprint,
records the decision, fires any side effects (Slack), and re-validates the contract to resolve
the incident or surface ``verify_failed``.
"""

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ApproveBody
from app.services import incident_service

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("")
def list_incidents(open: bool = Query(default=False, description="Only awaiting_approval, executing, verify_failed")):
    """Return incidents (most recent first). Use ``?open=true`` for the incidents table."""
    return [i.model_dump() for i in incident_service.list_incidents(open_only=open)]


@router.get("/{incident_id}")
def get_incident(incident_id: str):
    """Return the full incident detail (transcript + evidence); 404 if not found."""
    d = incident_service.get_incident(incident_id)
    if not d:
        from fastapi import HTTPException

        raise HTTPException(404, "not found")
    return d.model_dump()


@router.post("/approve-remediation")
def approve(body: ApproveBody):
    """Approve or reject a fingerprinted remediation and re-verify the contract (HITL gate)."""
    return incident_service.approve_remediation(body)

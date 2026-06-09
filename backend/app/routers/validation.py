"""Validation router — run contract checks and browse historical validation runs.

``POST /run`` validates every contract, persists each run, and opens an incident for any
failure (which triggers the agent investigation downstream). ``GET /results`` returns recent
runs for inspection in the UI.
"""

import json

from fastapi import APIRouter

from app.db import get_conn
from app.services.contracts_loader import load_all_contracts
from app.services.incident_service import create_incident_for_failure
from app.services.validation_engine import validate_contract
from app.services.validation_runs import persist_validation_run

router = APIRouter(prefix="/validation", tags=["validation"])


@router.post("/run")
def run_validation():
    """Run checks for all contracts; create incidents on failure."""
    results = []
    for contract in load_all_contracts():
        passed, details = validate_contract(contract)
        rid = persist_validation_run(contract.contract_id, passed, details)
        inc = None
        if not passed:
            inc = create_incident_for_failure(contract, passed, details)
        results.append(
            {
                "contract_id": contract.contract_id,
                "passed": passed,
                "validation_run_id": rid,
                "incident_id": inc.id if inc else None,
                "details": details,
            }
        )
    return {"results": results}


@router.get("/results")
def list_results(limit: int = 50, per_contract: bool = False):
    """Return validation runs. With ``per_contract=true``, one newest row per contract."""
    with get_conn() as conn:
        if per_contract:
            rows = conn.execute(
                """
                SELECT id, contract_id, passed, details, created_at
                FROM (
                    SELECT *,
                           ROW_NUMBER() OVER (
                               PARTITION BY contract_id
                               ORDER BY datetime(created_at) DESC
                           ) AS rn
                    FROM validation_runs
                )
                WHERE rn = 1
                ORDER BY contract_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM validation_runs ORDER BY datetime(created_at) DESC LIMIT ?",
                (limit,),
            ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "contract_id": r["contract_id"],
                "passed": bool(r["passed"]),
                "details": json.loads(r["details"] or "{}"),
                "created_at": r["created_at"],
            }
        )
    return out

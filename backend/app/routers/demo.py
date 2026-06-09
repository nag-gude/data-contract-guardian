"""Demo router — seed reproducible warehouse state so anyone can replay incidents.

The seed endpoints are **contract-driven**: passing/failing warehouse state is derived from each
contract's own schema and freshness window (see ``_passing_state`` / ``_failing_state``), so the
seeding scales to any number of tables and the resulting failures are real — never hand-faked —
which keeps the agent's downstream evidence honestly grounded.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from app.db import get_conn

from app.config import settings
from app.schemas import DataContract, MockWarehouseState, WarehouseStateBody
from app.services.contracts_loader import get_contract, load_all_contracts
from app.services.incident_service import create_incident_for_failure, prune_duplicate_incidents
from app.services.validation_engine import set_mock_warehouse_state, validate_contract
from app.services.validation_runs import persist_validation_run

router = APIRouter(prefix="/demo", tags=["demo"])

# Types that the validation engine treats as a numeric family — a column declared as one of
# these is the natural target for a "genuinely breaking" STRING type drift in the demo.
_NUMERIC_TYPES = {"FLOAT", "FLOAT64", "NUMERIC", "BIGNUMERIC", "DECIMAL"}

# Rough row magnitude for the network dataset so seeded warehouse state looks realistic.
_DATASET_ROWS = {"network": 2_400_000}


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _columns_and_types(contract: DataContract) -> tuple[list[str], dict[str, str]]:
    """Observed columns/types that satisfy the contract's declared schema."""
    cols = list(contract.schema_block.required_columns) if contract.schema_block else []
    declared = dict(contract.schema_block.column_types) if contract.schema_block else {}
    # Columns without a declared type default to STRING (passes — no type rule applies).
    types = {c: declared.get(c, "STRING") for c in cols}
    return cols, types


def _passing_state(contract: DataContract) -> MockWarehouseState:
    """Warehouse state that satisfies the contract: correct columns/types, fresh sync."""
    cols, types = _columns_and_types(contract)
    return MockWarehouseState(
        columns=cols,
        column_types=types,
        last_synced_at=_now_iso(),
        approx_row_count=_DATASET_ROWS.get(contract.bq_dataset, 1_000_000),
    )


def _failing_state(contract: DataContract) -> MockWarehouseState:
    """
    Derive a failing warehouse state from the contract itself, so the failures are real and
    the agent's evidence stays grounded regardless of which table it is:
      • freshness — synced well past the contract's own max_delay_minutes
      • schema    — the first numeric-typed column drifts to STRING (a genuinely breaking type),
                    yielding a schema_type_<col> failure; contracts with no numeric column simply
                    fail on freshness (a high-severity stale-sync incident).
    """
    cols, types = _columns_and_types(contract)

    declared = dict(contract.schema_block.column_types) if contract.schema_block else {}
    for col, declared_type in declared.items():
        if declared_type.upper() in _NUMERIC_TYPES and col in types:
            types[col] = "STRING"  # FLOAT/NUMERIC → STRING: a real, breaking type drift
            break

    max_delay = contract.freshness.max_delay_minutes if contract.freshness else 60
    stale = (datetime.now(timezone.utc) - timedelta(minutes=max_delay * 2 + 120)).isoformat()
    return MockWarehouseState(
        columns=cols,
        column_types=types,
        last_synced_at=stale,
        approx_row_count=_DATASET_ROWS.get(contract.bq_dataset, 1_000_000),
    )


@router.post("/warehouse-state")
def set_state(body: WarehouseStateBody):
    """Set an explicit, caller-supplied mock warehouse state for one contract."""
    st = MockWarehouseState(
        columns=body.columns,
        column_types=body.column_types or {},
        last_synced_at=body.last_synced_at,
        approx_row_count=body.approx_row_count,
    )
    set_mock_warehouse_state(body.contract_id, st)
    return {"ok": True, "contract_id": body.contract_id}


@router.post("/seed-failing/{contract_id}")
def seed_failing(contract_id: str):
    """Seed a contract-specific failing state (real schema/freshness violations)."""
    contract = get_contract(contract_id)
    if not contract:
        raise HTTPException(404, detail=f"contract not found: {contract_id}")
    set_mock_warehouse_state(contract_id, _failing_state(contract))
    return {"ok": True, "scenario": "failing", "contract_id": contract_id}


@router.post("/seed-passing/{contract_id}")
def seed_passing(contract_id: str):
    """Seed a contract-specific passing state (all checks satisfied)."""
    contract = get_contract(contract_id)
    if not contract:
        raise HTTPException(404, detail=f"contract not found: {contract_id}")
    set_mock_warehouse_state(contract_id, _passing_state(contract))
    return {"ok": True, "scenario": "passing", "contract_id": contract_id}


@router.post("/seed-all-failing")
def seed_all_failing():
    """Seed every contract into a failing state (one call to break the whole warehouse)."""
    out = []
    for c in load_all_contracts():
        set_mock_warehouse_state(c.contract_id, _failing_state(c))
        out.append(c.contract_id)
    return {"ok": True, "contract_ids": out}


@router.post("/seed-all-passing")
def seed_all_passing():
    """Seed every contract into a passing state (used to verify incidents resolve)."""
    out = []
    for c in load_all_contracts():
        set_mock_warehouse_state(c.contract_id, _passing_state(c))
        out.append(c.contract_id)
    return {"ok": True, "contract_ids": out}


@router.post("/prune-duplicate-incidents")
def prune_duplicates():
    """Cancel duplicate open incidents, keeping the newest per contract."""
    return prune_duplicate_incidents()


def _persist_validation_run(contract_id: str, passed: bool, details: dict) -> str:
    """Record a validation run and return its id (delegates to shared service)."""
    return persist_validation_run(contract_id, passed, details)


@router.post("/run-live-validation")
def run_live_validation(open_incidents: bool = True):
    """
    Validate all contracts against live BigQuery (MOCK_BIGQUERY=false).
    Does not seed mock warehouse state — reads INFORMATION_SCHEMA directly.
    """
    if settings.mock_bigquery:
        raise HTTPException(
            400,
            detail="Live validation requires MOCK_BIGQUERY=false and GCP_PROJECT_ID set.",
        )
    outcomes = []
    for contract in load_all_contracts():
        passed, details = validate_contract(contract)
        run_id = _persist_validation_run(contract.contract_id, passed, details)
        incident_id = None
        if not passed and open_incidents:
            inc = create_incident_for_failure(contract, passed, details)
            incident_id = inc.id if inc else None
        failed_checks = [c["name"] for c in details.get("checks", []) if not c.get("passed")]
        outcomes.append(
            {
                "contract_id": contract.contract_id,
                "passed": passed,
                "validation_run_id": run_id,
                "warehouse_source": details.get("warehouse_source"),
                "incident_id": incident_id,
                "error": details.get("error"),
                "failed_checks": failed_checks,
                "checks": details.get("checks", []),
            }
        )
    passed_n = sum(1 for o in outcomes if o["passed"])
    failed_n = len(outcomes) - passed_n
    return {
        "ok": True,
        "summary": {"total": len(outcomes), "passed": passed_n, "failed": failed_n},
        "outcomes": outcomes,
    }

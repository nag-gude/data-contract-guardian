"""Core contract validation engine.

Compares a ``DataContract``'s declared expectations against observed warehouse state — live
BigQuery (``INFORMATION_SCHEMA``) when configured, otherwise the SQLite-backed mock — and emits
a structured ``checks[]`` list (schema columns/types, freshness, volume, semantic SQL) plus an
overall pass/fail. The structured checks are what every downstream layer (severity, MCP
evidence grounding, RCA, remediations) keys off, so this module is the source of truth for
"what actually went wrong".
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.db import get_conn
from app.schemas import DataContract, MockWarehouseState
from app.services.bigquery_validation import bigquery_available, fetch_warehouse_state_from_bigquery, run_semantic_check


def _parse_ts(iso: str) -> datetime:
    """Parse an ISO-8601 timestamp (tolerating a trailing ``Z``) into an aware datetime."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def get_mock_warehouse_state(contract_id: str) -> MockWarehouseState | None:
    """Return the persisted mock warehouse state for a contract, or ``None`` if unseeded."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT payload FROM mock_warehouse_state WHERE contract_id = ?",
            (contract_id,),
        ).fetchone()
    if not row:
        return None
    return MockWarehouseState.model_validate_json(row["payload"])


def set_mock_warehouse_state(contract_id: str, state: MockWarehouseState) -> None:
    """Upsert the mock warehouse state for a contract (used by the demo seeders)."""
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO mock_warehouse_state (contract_id, payload, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(contract_id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
            """,
            (contract_id, state.model_dump_json(), now),
        )


def get_warehouse_state(contract: DataContract) -> tuple[MockWarehouseState | None, str]:
    """
    Resolve warehouse state: BigQuery INFORMATION_SCHEMA when live, else SQLite mock.
    Returns (state, source) where source is bigquery | mock | none.

    In live BigQuery mode we do not fall back to mock — missing tables must surface as failures
    against BigQuery, not as an unseeded mock warehouse.
    """
    if settings.use_live_bigquery and bigquery_available():
        bq_state = fetch_warehouse_state_from_bigquery(contract)
        if bq_state:
            return bq_state, "bigquery"
        return None, "bigquery"
    mock = get_mock_warehouse_state(contract.contract_id)
    if mock:
        return mock, "mock"
    return None, "none"


def validate_contract(contract: DataContract) -> tuple[bool, dict[str, Any]]:
    """Validate a contract against current warehouse state.

    Runs schema (required columns + type compatibility), freshness, volume, and semantic checks
    as declared by the contract. Returns ``(passed, details)`` where ``details["checks"]`` is the
    structured per-check result list and ``details["warehouse_source"]`` is ``bigquery``,
    ``mock``, or ``none``.
    """
    details: dict[str, Any] = {"checks": [], "warehouse_source": None}
    wh, source = get_warehouse_state(contract)
    details["warehouse_source"] = source

    if wh is None:
        if source == "bigquery":
            fq = f"{contract.bq_project}.{contract.bq_dataset}.{contract.bq_table}"
            details["error"] = (
                f"BigQuery table not found or has no columns: `{fq}`. "
                "Confirm Fivetran sync completed and table names match contract YAML."
            )
        else:
            details["error"] = (
                "No warehouse state. Seed mock: POST /api/demo/warehouse-state "
                "or set MOCK_BIGQUERY=false with GCP credentials."
            )
        return False, details

    ok = True
    if contract.schema_block and contract.schema_block.required_columns:
        missing = [c for c in contract.schema_block.required_columns if c not in wh.columns]
        check = {
            "name": "schema_required_columns",
            "passed": len(missing) == 0,
            "missing": missing,
            "source": source,
        }
        details["checks"].append(check)
        ok = ok and check["passed"]

        for col, expected in contract.schema_block.column_types.items():
            if col in wh.column_types:
                actual = wh.column_types[col]
                type_ok = actual.upper() == expected.upper() or _types_compatible(actual, expected)
                tcheck = {
                    "name": f"schema_type_{col}",
                    "passed": type_ok,
                    "expected": expected,
                    "actual": actual,
                    "source": source,
                }
                details["checks"].append(tcheck)
                ok = ok and type_ok

    if contract.freshness:
        try:
            last = _parse_ts(wh.last_synced_at)
            age_min = (datetime.now(timezone.utc) - last).total_seconds() / 60.0
            f_ok = age_min <= contract.freshness.max_delay_minutes
            details["checks"].append(
                {
                    "name": "freshness",
                    "passed": f_ok,
                    "age_minutes": round(age_min, 2),
                    "max_delay_minutes": contract.freshness.max_delay_minutes,
                    "source": source,
                }
            )
            ok = ok and f_ok
        except Exception as e:  # noqa: BLE001
            details["checks"].append({"name": "freshness", "passed": False, "error": str(e)})
            ok = False

    if contract.volume:
        details["checks"].append(
            {
                "name": "volume",
                "passed": True,
                "approx_row_count": wh.approx_row_count,
                "note": "Row count from warehouse metadata",
                "source": source,
            }
        )

    for sem in contract.semantic:
        if settings.use_live_bigquery and bigquery_available():
            sem_result = run_semantic_check(contract, sem.sql, sem.threshold)
            sem_result["name"] = f"semantic:{sem.name}"
            details["checks"].append(sem_result)
            ok = ok and sem_result.get("passed", False)
        else:
            details["checks"].append(
                {
                    "name": f"semantic:{sem.name}",
                    "passed": True,
                    "note": "Semantic check runs when MOCK_BIGQUERY=false with GCP credentials",
                    "sql": sem.sql,
                }
            )

    return ok, details


# BigQuery exposes the same physical type under multiple names. INFORMATION_SCHEMA reports the
# canonical GoogleSQL names (INT64, FLOAT64, BOOL), while contracts (and legacy SQL) often use the
# aliases (INTEGER, FLOAT, BOOLEAN). Normalise both sides to the canonical name before comparing so
# an INTEGER-vs-INT64 contract never raises a spurious type-mismatch incident.
_TYPE_ALIASES = {
    "INTEGER": "INT64",
    "INT": "INT64",
    "SMALLINT": "INT64",
    "BIGINT": "INT64",
    "TINYINT": "INT64",
    "BYTEINT": "INT64",
    "FLOAT": "FLOAT64",
    "DECIMAL": "NUMERIC",
    "BIGDECIMAL": "BIGNUMERIC",
    "BOOLEAN": "BOOL",
    "RECORD": "STRUCT",
}

# Numeric types that we treat as cross-compatible: a Fivetran sync that loads a value as INT64 or
# NUMERIC where the contract expected FLOAT64 is a benign widening, not a breaking drift.
_NUMERIC_FAMILY = {"INT64", "FLOAT64", "NUMERIC", "BIGNUMERIC"}


def _canonical_type(t: str) -> str:
    """Normalise a BigQuery type name to its canonical GoogleSQL form (e.g. INTEGER → INT64)."""
    base = t.upper().strip().split("(")[0].strip()  # drop precision, e.g. NUMERIC(10,2)
    return _TYPE_ALIASES.get(base, base)


def _types_compatible(actual: str, expected: str) -> bool:
    """True when the observed and expected column types are equivalent for contract purposes.

    Equivalence covers (1) exact match after alias normalisation (INT64 ≡ INTEGER, FLOAT64 ≡ FLOAT,
    BOOL ≡ BOOLEAN, …) and (2) widening within the numeric family (INT64/NUMERIC ↔ FLOAT64).
    """
    a, e = _canonical_type(actual), _canonical_type(expected)
    if a == e:
        return True
    return a in _NUMERIC_FAMILY and e in _NUMERIC_FAMILY

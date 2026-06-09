"""Persist validation run records."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.db import get_conn


def persist_validation_run(contract_id: str, passed: bool, details: dict[str, Any]) -> str:
    """Insert a validation run row and return its id."""
    rid = f"vr-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO validation_runs (id, contract_id, passed, details, created_at) VALUES (?,?,?,?,?)",
            (rid, contract_id, int(passed), json.dumps(details), now),
        )
    return rid

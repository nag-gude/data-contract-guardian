"""BigQuery warehouse validation — INFORMATION_SCHEMA checks when MOCK_BIGQUERY=false."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.schemas import DataContract, MockWarehouseState

logger = logging.getLogger(__name__)


def bigquery_available() -> bool:
    """True when live BigQuery is enabled (not mocked, a project is set, SDK importable)."""
    if settings.mock_bigquery or not settings.gcp_project_id:
        return False
    try:
        from google.cloud import bigquery  # noqa: F401

        return True
    except ImportError:
        return False


def fetch_warehouse_state_from_bigquery(contract: DataContract) -> MockWarehouseState | None:
    """
    Read column types from BigQuery INFORMATION_SCHEMA and table freshness from __TABLES__.
    Requires Application Default Credentials with bigquery.dataViewer + bigquery.jobUser.
    """
    if not bigquery_available():
        return None

    from google.cloud import bigquery

    client = bigquery.Client(project=contract.bq_project or settings.gcp_project_id)
    project = contract.bq_project
    dataset = contract.bq_dataset
    table = contract.bq_table

    col_query = f"""
        SELECT column_name, data_type
        FROM `{project}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
        WHERE table_name = @table_name
        ORDER BY ordinal_position
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("table_name", "STRING", table)]
    )
    rows = list(client.query(col_query, job_config=job_config).result())
    if not rows:
        return None

    columns = [r.column_name for r in rows]
    column_types = {r.column_name: r.data_type for r in rows}

    last_synced = datetime.now(timezone.utc).isoformat()
    row_count = 0
    try:
        meta_query = f"""
            SELECT TIMESTAMP_MILLIS(last_modified_time) AS last_modified, row_count
            FROM `{project}.{dataset}.__TABLES__`
            WHERE table_id = @table_id
        """
        meta_cfg = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("table_id", "STRING", table)]
        )
        meta_rows = list(client.query(meta_query, job_config=meta_cfg).result())
        if meta_rows:
            m = meta_rows[0]
            if m.last_modified:
                last_synced = m.last_modified.isoformat()
            row_count = int(m.row_count or 0)
    except Exception as exc:  # noqa: BLE001
        logger.debug("BigQuery __TABLES__ metadata skipped: %s", exc)

    return MockWarehouseState(
        columns=columns,
        column_types=column_types,
        last_synced_at=last_synced,
        approx_row_count=row_count,
    )


def run_semantic_check(contract: DataContract, sql: str, threshold: int = 0) -> dict[str, Any]:
    """Execute a semantic SQL check on BigQuery (COUNT-style rules)."""
    if not bigquery_available():
        return {"passed": True, "note": "BigQuery unavailable — semantic stub", "sql": sql}

    from google.cloud import bigquery

    client = bigquery.Client(project=contract.bq_project or settings.gcp_project_id)
    # Compose fully qualified table reference in SQL when the bare table name is used.
    # Use a word-boundary regex so substrings (e.g. "cdr" inside "cdr_archive") are
    # not corrupted, and skip rewriting if the table is already qualified/backticked.
    fq = f"`{contract.bq_project}.{contract.bq_dataset}.{contract.bq_table}`"
    pattern = re.compile(rf"(?<![\w.`]){re.escape(contract.bq_table)}(?![\w.`])")
    rendered = pattern.sub(fq, sql)

    try:
        result = list(client.query(rendered).result())
        value = int(result[0][0]) if result else 0
        passed = value <= threshold
        return {"passed": passed, "value": value, "threshold": threshold, "sql": rendered}
    except Exception as exc:  # noqa: BLE001
        return {"passed": False, "error": str(exc)[:300], "sql": rendered}

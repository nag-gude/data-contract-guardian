"""SQLite persistence for Data Contract Guardian.

A deliberately small, dependency-free store for demo/dev state: incidents and their
agent-step events, Fivetran MCP evidence bundles, validation runs, HITL approvals, mock
warehouse state, and resolution memory. The schema is created lazily on first connection and
the database lives at ``settings.database_path`` (``/tmp`` in containers).

Note: single-file SQLite is fine for a single Cloud Run instance / demo, but is not durable
across multiple revisions — swap for Cloud SQL or Firestore for multi-instance deployments.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.config import settings


def _ensure_parent(path: Path) -> None:
    """Create the parent directory of ``path`` if it does not yet exist."""
    path.parent.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    """Create all tables if absent (idempotent). Safe to call repeatedly."""
    _ensure_parent(settings.database_path)
    with sqlite3.connect(settings.database_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY,
                contract_id TEXT NOT NULL,
                fivetran_connector_id TEXT,
                severity TEXT NOT NULL,
                status TEXT NOT NULL,
                root_cause TEXT,
                confidence REAL,
                remediation_status TEXT,
                evidence_bundle_ids TEXT,
                action_fingerprint TEXT,
                ranked_remediations TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS incident_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (incident_id) REFERENCES incidents(id)
            );

            CREATE TABLE IF NOT EXISTS evidence_bundles (
                id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (incident_id) REFERENCES incidents(id)
            );

            CREATE TABLE IF NOT EXISTS validation_runs (
                id TEXT PRIMARY KEY,
                contract_id TEXT NOT NULL,
                passed INTEGER NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT NOT NULL,
                action_fingerprint TEXT NOT NULL,
                approver_id TEXT NOT NULL,
                approved INTEGER NOT NULL,
                idempotency_key TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(incident_id, idempotency_key)
            );

            CREATE TABLE IF NOT EXISTS mock_warehouse_state (
                contract_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS resolution_memory (
                id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                remediation_signature TEXT,
                outcome TEXT NOT NULL,
                time_to_verify_ms INTEGER,
                approver_id TEXT,
                closed_at TEXT NOT NULL
            );
            """
        )
        conn.commit()


_schema_ready = False


def _ensure_schema() -> None:
    """Create tables once per process, not on every connection."""
    global _schema_ready
    if not _schema_ready:
        init_db()
        _schema_ready = True


@contextmanager
def get_conn():
    """Yield a row-factory SQLite connection, committing on success and always closing.

    Ensures the schema exists (once per process) before handing out the connection, so callers
    never have to bootstrap tables themselves.
    """
    _ensure_schema()
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a ``sqlite3.Row`` into a plain ``dict`` keyed by column name."""
    return {k: row[k] for k in row.keys()}

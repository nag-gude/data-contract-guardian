"""Shared Pydantic models for Data Contract Guardian.

Three families of models:
  • **Contract definitions** — ``DataContract`` and its rule blocks (``FreshnessRule``,
    ``SchemaRule``, ``VolumeRule``, ``SemanticRule``) parsed from the YAML files in
    ``contracts/``. Note ``DataContract.schema_block`` is aliased to ``schema`` in YAML to
    avoid colliding with Pydantic's reserved ``schema`` attribute.
  • **Runtime/evidence models** — ``MockWarehouseState``, ``EvidenceBundlePayload``,
    ``RemediationOption``, ``IncidentPublic`` / ``IncidentDetail``, ``ValidationRunPublic``.
  • **Request/response bodies** — ``ApproveBody``, ``WarehouseStateBody``, ``AgentRunBody``,
    ``AgentRunResult`` used by the routers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, ConfigDict


def utc_now() -> str:
    """Current UTC time as an ISO-8601 string (the timestamp format used throughout)."""
    return datetime.now(timezone.utc).isoformat()


class FreshnessRule(BaseModel):
    """Contract freshness expectation: warehouse data must be at most N minutes stale."""

    max_delay_minutes: int = 30


class SchemaRule(BaseModel):
    """Contract schema expectations: required columns, expected types, and nullability."""

    required_columns: list[str] = Field(default_factory=list)
    column_types: dict[str, str] = Field(default_factory=dict)
    nullable: dict[str, bool] = Field(default_factory=dict)


class VolumeRule(BaseModel):
    """Contract volume expectation: tolerated day-over-day row-count variance (percent)."""

    daily_row_variance_percent: float = 20.0


class SemanticRule(BaseModel):
    """A named SQL business-rule check; passes when its COUNT result is <= ``threshold``."""

    name: str
    sql: str
    threshold: int = 0


class DataContract(BaseModel):
    """A versioned data contract: the warehouse target plus the rule blocks to enforce.

    Loaded from a YAML/JSON file in ``contracts/``. ``populate_by_name`` + the ``schema`` alias
    let the YAML use the natural key ``schema`` while the attribute is ``schema_block``.
    """

    model_config = ConfigDict(populate_by_name=True)

    contract_id: str
    warehouse: str = "bigquery"
    fivetran_connector_id: str
    bq_project: str
    bq_dataset: str
    bq_table: str
    freshness: FreshnessRule | None = None
    schema_block: SchemaRule | None = Field(default=None, alias="schema")
    volume: VolumeRule | None = None
    semantic: list[SemanticRule] = Field(default_factory=list)


class MockWarehouseState(BaseModel):
    """Simulated INFORMATION_SCHEMA + table stats for the MVP (no BigQuery required)."""

    columns: list[str]
    column_types: dict[str, str] = Field(default_factory=dict)
    last_synced_at: str  # ISO
    approx_row_count: int = 0


class EvidenceBundlePayload(BaseModel):
    """One persisted unit of investigation evidence (e.g. a Fivetran MCP tool result)."""

    bundle_id: str
    source: str  # fivetran_mcp | bigquery_mock
    tool_name: str
    connector_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class RemediationOption(BaseModel):
    """A ranked, risk-classified remediation the agent proposes for human approval."""

    rank: int
    title: str
    risk_class: str  # R0-R4
    rationale: str


class IncidentPublic(BaseModel):
    """Incident summary as returned by list endpoints (no events/evidence detail)."""

    id: str
    contract_id: str
    fivetran_connector_id: str | None
    severity: str
    status: str
    root_cause: str | None
    confidence: float | None
    remediation_status: str | None
    evidence_bundle_ids: list[str]
    action_fingerprint: str | None
    ranked_remediations: list[RemediationOption] = Field(default_factory=list)
    created_at: str
    updated_at: str


class IncidentDetail(IncidentPublic):
    """Full incident view: summary plus the agent transcript (``events``) and ``evidence``."""

    events: list[dict[str, Any]]
    evidence: list[dict[str, Any]]


class ValidationRunPublic(BaseModel):
    """A single persisted validation run with its structured check details."""

    id: str
    contract_id: str
    passed: bool
    details: dict[str, Any]
    created_at: str


class ApproveBody(BaseModel):
    """HITL approve/reject request; the fingerprint must match the incident's proposed action."""

    incident_id: str
    action_fingerprint: str
    approver_id: str
    approve: bool = True
    idempotency_key: str | None = None


class WarehouseStateBody(BaseModel):
    """Request body for seeding mock warehouse state for one contract (demo)."""

    contract_id: str
    columns: list[str]
    column_types: dict[str, str] | None = None
    last_synced_at: str
    approx_row_count: int = 0


class AgentRunBody(BaseModel):
    """Request body for a single-contract agent investigation."""

    contract_id: str
    open_incident: bool = False
    require_failure: bool = False


class AgentRunResult(BaseModel):
    """Full result of an agent investigation: transcript, evidence, RCA, and proposals."""

    contract_id: str
    validation_passed: bool
    validation_details: dict[str, Any] = Field(default_factory=dict)
    incident_id: str | None = None
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    evidence_bundles: list[dict[str, Any]] = Field(default_factory=list)
    root_cause: str | None = None
    confidence: float | None = None
    stakeholder_summary: str | None = None
    severity: str | None = None
    ranked_remediations: list[dict[str, Any]] = Field(default_factory=list)
    action_fingerprint: str | None = None
    orchestrator: str | None = None
    platform: dict[str, Any] | None = None
    capability: str | None = None
    disclaimer: str | None = None
    mcp_trace: list[dict[str, Any]] = Field(default_factory=list)
    summary_for_agent: dict[str, Any] | None = None
    connector_context: dict[str, Any] | None = None
    schema_investigation: dict[str, Any] | None = None

"""Tests for core agent behaviour and integrations.

Exercises the invariants the product depends on: Fivetran MCP transport selection (mock vs live
stdio), ADK availability, the ``/platform`` integration-status endpoint, evidence grounded in the
actual failing checks, failure-type-aware remediations, Gemini backend resolution, and the
end-to-end seed → agent pipeline → incident flow. Runs fully offline with mock Fivetran MCP and
mock BigQuery (set at import time below).
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_PATH", "/tmp/guardian-test.db")
os.environ.setdefault("MOCK_FIVETRAN_MCP", "true")
os.environ.setdefault("MOCK_BIGQUERY", "true")

from app.main import app  # noqa: E402
from app.services.agent_rca import build_ranked_remediations
from app.services.fivetran_mcp import MCP_INVESTIGATION_TOOLS, fetch_investigation_evidence, mcp_transport_status
from app.services.fivetran_mcp_stdio import mcp_stdio_available
from app.services.gemini_client import resolve_backend
from app.services.validation_engine import _types_compatible
from agent_builder.mcp_config import adk_available


@pytest.fixture
def client():
    """A FastAPI ``TestClient`` bound to the application."""
    return TestClient(app)


def test_adk_installed():
    """The Google ADK SDK must be importable for the Agent Builder path."""
    assert adk_available() is True


def test_types_compatible_numeric_family():
    """NUMERIC/FLOAT are treated as compatible; STRING/FLOAT is a real mismatch."""
    assert _types_compatible("NUMERIC", "FLOAT") is True
    assert _types_compatible("STRING", "FLOAT") is False


def test_types_compatible_bigquery_aliases():
    """BigQuery alias names must not raise spurious mismatches (INT64 ≡ INTEGER, etc.)."""
    assert _types_compatible("INT64", "INTEGER") is True
    assert _types_compatible("INTEGER", "INT64") is True
    assert _types_compatible("FLOAT64", "FLOAT") is True
    assert _types_compatible("BOOL", "BOOLEAN") is True
    assert _types_compatible("NUMERIC(10, 2)", "NUMERIC") is True
    assert _types_compatible("STRING", "INT64") is False


def test_mcp_transport_status_mock():
    """With no credentials the transport reports the MCP protocol/server but mock mode."""
    status = mcp_transport_status()
    assert status["protocol"] == "Model Context Protocol"
    assert status["server"] == "github.com/fivetran/fivetran-mcp"
    assert status["transport"] == "mock"


def test_mcp_stdio_not_used_when_mock():
    """The live stdio path is inactive while mock mode is on."""
    assert mcp_stdio_available() is False


def test_mcp_discovery_endpoint(client):
    """MCP discovery runs five read-only Fivetran tools and returns trace."""
    r = client.post("/api/agent/mcp-discovery")
    assert r.status_code == 200
    data = r.json()
    assert data["capability"] == "mcp_discovery"
    assert data["tools_run"] == 5
    assert len(data["mcp_trace"]) == 5
    tools = {t["tool"] for t in data["mcp_trace"]}
    assert tools == {
        "get_account_info",
        "list_connections",
        "get_connection_details",
        "get_connection_state",
        "list_destinations",
    }


def test_platform_status_reports_capabilities(client):
    """The platform endpoint reports integrations, workflow counters, and capability tag."""
    r = client.get("/api/agent/platform")
    assert r.status_code == 200
    data = r.json()
    assert data["fivetran_mcp"]["protocol"] == "Model Context Protocol"
    assert "get_account_info" in data["fivetran_mcp"]["tools"]
    assert len(data["fivetran_mcp"]["tools"]) == 5
    assert data["agent_builder"]["adk_installed"] is True
    assert "model" in data["gemini"]
    assert "mock_mode" in data["bigquery"]
    assert data.get("capability") == "platform_status"
    assert "workflow" in data
    assert "validation_runs" in data["workflow"]


def test_discover_endpoint_read_only(client):
    """Discover validates + investigates without opening incidents."""
    client.post("/api/demo/seed-all-failing")
    r = client.post("/api/agent/discover/network_alarm_v1")
    assert r.status_code == 200
    data = r.json()
    assert data["capability"] == "investigate_only"
    assert data["validation_passed"] is False
    assert len(data["mcp_trace"]) == 3
    assert data["summary_for_agent"]["incident_id"] is None
    assert "failed_checks" in data["summary_for_agent"]


def test_agent_rejects_approval_fields(client):
    """Investigate rejects execution-shaped bodies."""
    r = client.post(
        "/api/agent/investigate",
        json={"contract_id": "network_alarm_v1", "approve": True, "action_fingerprint": "x"},
    )
    assert r.status_code == 400


def test_investigate_includes_mcp_trace(client):
    """Investigate responses include mcp_trace and summary_for_agent."""
    client.post("/api/demo/seed-all-failing")
    r = client.post(
        "/api/agent/investigate",
        json={"contract_id": "network_alarm_v1", "open_incident": False},
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["mcp_trace"]) == 3
    assert data["summary_for_agent"]["failed_check_count"] >= 1


def test_build_mcp_trace_from_mock_bundles():
    """MCP trace summarizes mock bundles as ok."""
    from app.services.agent_response import build_mcp_trace
    from app.services.fivetran_mcp import fetch_investigation_evidence

    bundles = fetch_investigation_evidence("ft_airtable_network", failed_checks=["freshness"])
    trace = build_mcp_trace(bundles)
    assert len(trace) == 3
    assert all(t["ok"] for t in trace)
    assert trace[0]["tool"] in {"get_connection_details", "get_connection_state", "get_connection_schema_config"}


def test_mcp_investigation_mock_bundles():
    """Investigation returns one mock bundle per MCP tool."""
    bundles = fetch_investigation_evidence("ft_airtable_network", drift_mode=True)
    assert len(bundles) == len(MCP_INVESTIGATION_TOOLS)
    assert all(b.data.get("mcp_mode") == "mock" for b in bundles)


def test_connection_state_enriched_when_state_endpoint_405(monkeypatch):
    """Airtable connectors return 405 on /state — fall back to connection details."""
    monkeypatch.setattr("app.config.settings.mock_fivetran_mcp", False)
    monkeypatch.setattr("app.config.settings.fivetran_api_key", "k")
    monkeypatch.setattr("app.config.settings.fivetran_api_secret", "s")

    def fake_stdio(tool_name: str, arguments: dict):
        if tool_name == "get_connection_state":
            return {
                "is_error": False,
                "text": "Fivetran API error: 405 - HTTP 405 Method Not Allowed",
                "content": [],
            }
        if tool_name == "get_connection_details":
            return {
                "is_error": False,
                "text": (
                    '{"data": {"id": "toll_donator", "service": "airtable", '
                    '"status": {"sync_state": "scheduled", "setup_state": "connected"}}}'
                ),
                "content": [],
            }
        return {"is_error": False, "text": "{}", "content": []}

    with patch("app.services.fivetran_mcp_stdio.call_fivetran_mcp_tool_stdio", side_effect=fake_stdio), patch(
        "app.services.fivetran_connection_resolver.resolve_fivetran_connection_id",
        return_value="toll_donator",
    ):
        from app.services.fivetran_mcp import call_mcp_tool

        bundle = call_mcp_tool("get_connection_state", "ft_airtable_network")
        assert bundle.data["mcp_mode"] == "live_stdio_enriched"
        assert bundle.data["fivetran_response"]["sync_state"] == "scheduled"
        assert bundle.data["fivetran_response"]["enriched_from"] == "get_connection_details"


def test_stdio_mcp_bundle_when_live(monkeypatch):
    """With credentials and a patched stdio call, bundles are tagged ``live_stdio``."""
    monkeypatch.setattr("app.config.settings.mock_fivetran_mcp", False)
    monkeypatch.setattr("app.config.settings.fivetran_api_key", "k")
    monkeypatch.setattr("app.config.settings.fivetran_api_secret", "s")

    fake = {
        "mcp_protocol": "Model Context Protocol",
        "mcp_transport": "stdio",
        "text": '{"status":"ok"}',
        "is_error": False,
        "content": [],
    }

    with patch("app.services.fivetran_mcp_stdio.call_fivetran_mcp_tool_stdio", return_value=fake), patch(
        "app.services.fivetran_connection_resolver.resolve_fivetran_connection_id",
        return_value="conn-1",
    ):
        from app.services.fivetran_mcp import call_mcp_tool

        bundle = call_mcp_tool("get_connection_details", "conn-1")
        assert bundle.data["mcp_mode"] == "live_stdio"
        assert bundle.data["mcp_protocol"] == "Model Context Protocol"


def _schema_config(bundles):
    """The ``get_connection_schema_config`` bundle from an investigation evidence list."""
    return next(b for b in bundles if b.tool_name == "get_connection_schema_config")


def _connection_details(bundles):
    """The ``get_connection_details`` bundle from an investigation evidence list."""
    return next(b for b in bundles if b.tool_name == "get_connection_details")


def test_evidence_grounded_in_freshness_only():
    """Freshness-only failure → stale sync evidence, but NO fabricated type-mismatch."""
    bundles = fetch_investigation_evidence("ft_airtable_network", failed_checks=["freshness"])
    assert _connection_details(bundles).data["sync_status"] == "failed"
    assert _schema_config(bundles).data["recent_errors"] == []


def test_evidence_grounded_in_schema_only():
    """Schema-only failure → type-mismatch evidence, but sync reported healthy (not stale)."""
    bundles = fetch_investigation_evidence("ft_airtable_network", failed_checks=["schema_type_charge_amount"])
    assert _schema_config(bundles).data["recent_errors"]
    assert _connection_details(bundles).data["sync_status"] == "healthy"


def test_remediations_vary_by_failure_type():
    """Schema drift leads with a SAFE_CAST MR for the failed column; freshness leads with sync remediation."""
    schema_details = {
        "checks": [
            {
                "name": "schema_type_charge_amount",
                "passed": False,
                "expected": "FLOAT",
                "actual": "STRING",
            }
        ]
    }
    schema = build_ranked_remediations(
        "rc",
        failed_checks=["schema_type_charge_amount"],
        validation_details=schema_details,
    )
    fresh = build_ranked_remediations("rc", failed_checks=["freshness"])
    assert "charge_amount" in schema[0].title
    assert "FLOAT" in schema[0].title
    assert any("sync" in r.title.lower() for r in fresh)
    assert [r.rank for r in schema] == list(range(1, len(schema) + 1))


def test_freshness_remediation_paused_connector():
    """Paused connector → resume sync (R4)."""
    evidence = [
        {
            "tool_name": "get_connection_details",
            "data": {
                "fivetran_response": {
                    "data": {
                        "id": "toll_donator",
                        "paused": True,
                        "succeeded_at": "2026-06-09T19:35:56Z",
                        "status": {"sync_state": "paused"},
                    }
                }
            },
        }
    ]
    details = {"checks": [{"name": "freshness", "passed": False, "age_minutes": 49, "max_delay_minutes": 30}]}
    rems = build_ranked_remediations(
        "rc",
        failed_checks=["freshness"],
        validation_details=details,
        evidence_bundles=evidence,
    )
    assert "Resume paused" in rems[0].title
    assert rems[0].risk_class == "R4"


def test_freshness_remediation_healthy_connector():
    """Active connector with stale BQ → manual sync / ingestion lag (not resume paused)."""
    evidence = [
        {
            "tool_name": "get_connection_state",
            "data": {
                "fivetran_response": {
                    "connection_id": "toll_donator",
                    "sync_state": "scheduled",
                    "paused": False,
                    "succeeded_at": "2026-06-09T19:35:56Z",
                    "enriched_from": "get_connection_details",
                }
            },
        }
    ]
    details = {"checks": [{"name": "freshness", "passed": False, "age_minutes": 49, "max_delay_minutes": 30}]}
    rems = build_ranked_remediations(
        "rc",
        failed_checks=["freshness"],
        validation_details=details,
        evidence_bundles=evidence,
    )
    assert "ingestion lag" in rems[0].title.lower() or "manual" in rems[0].title.lower()
    assert "Resume paused" not in rems[0].title
    assert rems[0].risk_class == "R3"


def test_remediations_bind_multiple_failed_columns():
    """Each schema_type_* failure gets its own column-specific remediation."""
    details = {
        "checks": [
            {"name": "schema_type_duration_seconds", "passed": False, "expected": "INTEGER", "actual": "STRING"},
            {"name": "schema_type_bytes_transferred", "passed": False, "expected": "INTEGER", "actual": "STRING"},
        ]
    }
    failed = ["schema_type_duration_seconds", "schema_type_bytes_transferred"]
    rems = build_ranked_remediations("rc", failed_checks=failed, validation_details=details)
    assert "duration_seconds" in rems[0].title
    assert "bytes_transferred" in rems[1].title


def test_mcp_tool_arguments_include_schema_file():
    """GitHub fivetran-mcp requires schema_file on every investigation tool call."""
    from app.services.fivetran_mcp_stdio import build_tool_arguments

    args = build_tool_arguments("get_connection_details", "my_connection")
    assert args["schema_file"] == "open-api-definitions/connections/connection_details.json"
    assert args["connection_id"] == "my_connection"


def test_agent_pipeline_e2e(client):
    """Seeding all contracts failing and running the pipeline yields grounded, critical incidents."""
    client.post("/api/demo/seed-all-failing")
    r = client.post("/api/agent/run-pipeline")
    assert r.status_code == 200
    failed = [o for o in r.json()["outcomes"] if not o["validation_passed"]]
    assert failed[0]["transcript_steps"] >= 5
    assert failed[0]["mcp_bundles"] == 3
    # Seeded failing state now drives a real schema/type failure → critical severity
    assert any(o["severity"] == "critical" for o in failed)


def test_gemini_backend_resolves():
    """Backend resolution always returns a known value, even with no credentials."""
    assert resolve_backend() in {"vertex_ai", "ai_studio", "none"}


def test_gemini_json_parsing_robust():
    """RCA JSON parses whether returned raw, fenced, or wrapped in prose."""
    from app.services.gemini_client import _parse_json

    assert _parse_json('{"root_cause": "x", "confidence": 0.9}')["root_cause"] == "x"
    assert _parse_json('```json\n{"a": 1}\n```')["a"] == 1
    assert _parse_json('Here is the result:\n{"a": 2}\nThanks')["a"] == 2
    assert _parse_json("not json at all") is None


def test_gemini_status_reports_sdk_and_fallback():
    """Status surfaces the google-genai SDK and the configured fallback model."""
    from app.services.gemini_client import gemini_status

    s = gemini_status()
    assert s["sdk"] == "google-genai"
    assert "fallback_model" in s


def test_incident_dedup_on_repeated_failure(client):
    """Repeated pipeline runs reuse the open incident instead of creating duplicates."""
    from app.services.incident_service import find_open_incident

    client.post("/api/demo/seed-all-failing")
    contract_id = "network_alarm_v1"
    client.post("/api/agent/run-pipeline")
    first_id = find_open_incident(contract_id)
    assert first_id is not None
    client.post("/api/agent/run-pipeline")
    second_id = find_open_incident(contract_id)
    assert second_id == first_id
    listed = client.get("/api/incidents").json()
    open_alarm = [i for i in listed if i["contract_id"] == contract_id and i["status"] == "awaiting_approval"]
    assert len(open_alarm) == 1

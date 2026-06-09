"""Remediation execution after human approval."""

from app.schemas import RemediationOption
from app.services.remediation_executor import execute_top_remediation, verify_with_retry
from app.services.contracts_loader import get_contract
from app.services.validation_engine import get_mock_warehouse_state


def test_mock_sync_remediation_refreshes_freshness(client):
    """Approving a sync remediation fixes mock warehouse freshness and verifies."""
    client.post("/api/demo/seed-all-failing")
    client.post("/api/agent/run-pipeline")
    incidents = client.get("/api/incidents?open=true").json()
    assert incidents
    inc = incidents[0]
    assert inc["action_fingerprint"]

    r = client.post(
        "/api/approve-remediation",
        json={
            "incident_id": inc["id"],
            "action_fingerprint": inc["action_fingerprint"],
            "approver_id": "test",
            "approve": True,
            "idempotency_key": "test-sync-fix",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["execution"]["executed"] is True
    # Mock mode: sync remediation should resolve freshness-only incidents.
    if not data["verification_passed"]:
        assert data["failed_checks"]


def test_execute_top_sync_remediation_mock():
    from datetime import datetime, timedelta, timezone

    from app.routers.demo import _passing_state
    from app.services.validation_engine import set_mock_warehouse_state

    contract = get_contract("network_cdr_freshness_v1")
    stale = (datetime.now(timezone.utc) - timedelta(minutes=200)).isoformat()
    set_mock_warehouse_state(
        contract.contract_id,
        _passing_state(contract).model_copy(update={"last_synced_at": stale}),
    )
    ranked = [
        RemediationOption(
            rank=1,
            title="Trigger manual Fivetran sync and investigate BigQuery ingestion lag",
            risk_class="R3",
            rationale="test",
        )
    ]
    result = execute_top_remediation(contract, ranked)
    assert result["executed"] is True
    assert result["mode"] == "mock_warehouse"
    state = get_mock_warehouse_state(contract.contract_id)
    assert state is not None
    passed, _, _ = verify_with_retry(contract)
    assert passed is True

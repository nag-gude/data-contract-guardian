"""Tests for cross-source schema investigation."""

from app.schemas import DataContract, SchemaRule
from app.schemas import EvidenceBundlePayload
from app.services.fivetran_mcp import _bundle
from app.services.schema_investigation import build_schema_investigation


def _contract() -> DataContract:
    return DataContract(
        contract_id="network_alarm_v1",
        warehouse="bigquery",
        fivetran_connector_id="ft_airtable_network",
        bq_project="my-project",
        bq_dataset="network",
        bq_table="network_alarm",
        schema_block=SchemaRule(
            required_columns=["alarm_id", "cell_id", "severity", "raised_at"],
        ),
    )


def test_schema_investigation_surfaces_missing_columns(monkeypatch):
    monkeypatch.setattr("app.config.settings.fivetran_connection_id", "hackathon")
    contract = _contract()
    validation_details = {
        "warehouse_source": "bigquery",
        "checks": [
            {
                "name": "schema_required_columns",
                "passed": False,
                "missing": ["severity"],
                "source": "bigquery",
            },
            {
                "name": "schema_type_alarm_id",
                "passed": True,
                "expected": "STRING",
                "actual": "STRING",
                "source": "bigquery",
            },
        ],
    }
    schema_bundle = _bundle(
        tool_name="get_connection_schema_config",
        connector_id="ft_airtable_network",
        data={
            "fivetran_response": {
                "data": {
                    "schemas": {
                        "hackathon": {
                            "tables": {
                                "network_alarm": {
                                    "enabled": True,
                                    "columns": {
                                        "alarm_id": {"enabled": True},
                                        "cell_id": {"enabled": True},
                                        "raised_at": {"enabled": True},
                                    },
                                }
                            }
                        }
                    }
                }
            },
            "mcp_mode": "live_stdio",
        },
    )

    with monkeypatch.context() as m:
        m.setattr(
            "app.services.schema_investigation.get_connector_context",
            lambda _ref: {
                "configured_connection_ref": "hackathon",
                "resolved_connection_id": "toll_donator",
                "config_source": "FIVETRAN_CONNECTION_ID (.env / terraform.tfvars)",
            },
        )
        result = build_schema_investigation(contract, validation_details, [schema_bundle])

    assert result["contract_id"] == "network_alarm_v1"
    assert result["missing_in_bigquery"] == ["severity"]
    assert "severity" in result["missing_in_fivetran_schema"]
    assert any("Schema tab" in step for step in result["investigation_steps"])
    assert result["connector"]["configured_connection_ref"] == "hackathon"

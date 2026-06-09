"""Cross-source schema investigation: contract YAML vs Fivetran MCP vs BigQuery."""

from __future__ import annotations

from typing import Any

from app.schemas import DataContract, EvidenceBundlePayload
from app.services.fivetran_connection_resolver import get_connector_context


def _warehouse_columns(validation_details: dict[str, Any]) -> list[str]:
    cols: set[str] = set()
    for check in validation_details.get("checks", []):
        if check.get("name", "").startswith("schema_type_"):
            col = check["name"][len("schema_type_") :]
            cols.add(col)
        if check.get("name") == "schema_required_columns" and check.get("missing"):
            for col in check["missing"]:
                cols.add(col)
    return sorted(cols)


def _contract_required_columns(contract: DataContract) -> list[str]:
    if contract.schema_block and contract.schema_block.required_columns:
        return list(contract.schema_block.required_columns)
    return []


def _fivetran_schema_bundle(bundles: list[EvidenceBundlePayload]) -> EvidenceBundlePayload | None:
    for bundle in bundles:
        if bundle.tool_name == "get_connection_schema_config":
            return bundle
    return None


def _extract_fivetran_columns(schema_data: dict[str, Any], table_name: str) -> list[str]:
    """Parse enabled columns for ``table_name`` from get_connection_schema_config payload."""
    columns: set[str] = set()

    tables_enabled = schema_data.get("tables_enabled")
    if isinstance(tables_enabled, list):
        for entry in tables_enabled:
            if isinstance(entry, str) and entry == table_name:
                return [table_name]
            if isinstance(entry, dict) and entry.get("table") == table_name:
                cols = entry.get("columns")
                if isinstance(cols, list):
                    return sorted(str(c) for c in cols)

    resp = schema_data.get("fivetran_response") or schema_data
    inner = resp.get("data", resp) if isinstance(resp, dict) else {}
    schemas = inner.get("schemas") if isinstance(inner, dict) else None
    if not isinstance(schemas, dict):
        return []

    for _schema_name, schema_body in schemas.items():
        if not isinstance(schema_body, dict):
            continue
        tables = schema_body.get("tables") or {}
        if not isinstance(tables, dict):
            continue
        table_cfg = tables.get(table_name)
        if not isinstance(table_cfg, dict):
            continue
        if table_cfg.get("enabled") is False:
            continue
        table_columns = table_cfg.get("columns") or {}
        if isinstance(table_columns, dict):
            for col_name, col_cfg in table_columns.items():
                if isinstance(col_cfg, dict) and col_cfg.get("enabled") is False:
                    continue
                columns.add(str(col_name))
        break

    return sorted(columns)


def build_schema_investigation(
    contract: DataContract,
    validation_details: dict[str, Any],
    evidence_bundles: list[EvidenceBundlePayload],
) -> dict[str, Any]:
    """
    Compare contract required columns with Fivetran schema config and BigQuery warehouse checks.

    Intended for schema-drift incidents (e.g. ``network_alarm_v1``) and surfaces explicit
    missing-column lists plus Fivetran UI review steps.
    """
    required = _contract_required_columns(contract)
    warehouse_cols = _warehouse_columns(validation_details)
    missing_check = next(
        (c for c in validation_details.get("checks", []) if c.get("name") == "schema_required_columns"),
        {},
    )
    missing_in_bq = list(missing_check.get("missing") or [])

    schema_bundle = _fivetran_schema_bundle(evidence_bundles)
    fivetran_cols: list[str] = []
    fivetran_schema_ok = False
    if schema_bundle and not schema_bundle.data.get("is_error"):
        fivetran_cols = _extract_fivetran_columns(schema_bundle.data, contract.bq_table)
        fivetran_schema_ok = bool(fivetran_cols)

    missing_in_fivetran = [c for c in required if fivetran_cols and c not in fivetran_cols]
    connector = get_connector_context(contract.fivetran_connector_id)

    investigation_steps = [
        (
            f"Open Fivetran UI → connector `{connector['resolved_connection_id']}` "
            f"(configured ref: `{connector.get('configured_connection_ref') or 'auto'}`) → Schema tab "
            f"for table `{contract.bq_table}`."
        ),
        f"Review sync logs for `{contract.contract_id}` / `{contract.bq_table}` in the Fivetran UI.",
        "Verify the source system (Airtable) still exposes required columns: "
        + ", ".join(required)
        + ".",
        (
            f"Compare BigQuery `{contract.bq_project}.{contract.bq_dataset}.{contract.bq_table}` "
            f"({validation_details.get('warehouse_source', 'unknown')} source) against the contract."
        ),
    ]

    return {
        "contract_id": contract.contract_id,
        "table": contract.bq_table,
        "bq_table_fqn": f"{contract.bq_project}.{contract.bq_dataset}.{contract.bq_table}",
        "connector": connector,
        "required_columns": required,
        "bigquery_columns_observed": warehouse_cols,
        "missing_in_bigquery": missing_in_bq,
        "fivetran_columns_enabled": fivetran_cols,
        "missing_in_fivetran_schema": missing_in_fivetran,
        "fivetran_schema_config_available": fivetran_schema_ok,
        "investigation_steps": investigation_steps,
        "likely_root_causes": _likely_root_causes(
            missing_in_bq=missing_in_bq,
            missing_in_fivetran=missing_in_fivetran,
            failed_checks=[c for c in validation_details.get("checks", []) if not c.get("passed")],
        ),
    }


def _likely_root_causes(
    *,
    missing_in_bq: list[str],
    missing_in_fivetran: list[str],
    failed_checks: list[dict[str, Any]],
) -> list[str]:
    causes: list[str] = []
    if missing_in_fivetran:
        causes.append(
            "Columns disabled or absent in Fivetran schema config — re-enable in the Schema tab."
        )
    if missing_in_bq and not missing_in_fivetran:
        causes.append(
            "Fivetran schema includes columns but BigQuery is missing them — check sync logs and recent sync errors."
        )
    if any(c.get("name", "").startswith("schema_type_") for c in failed_checks):
        causes.append("Column type drift between source and BigQuery — review upstream type changes.")
    if not causes and missing_in_bq:
        causes.append(
            "Required columns missing from BigQuery — confirm source schema and Fivetran sync completed."
        )
    return causes

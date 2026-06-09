# Target table schemas (align Airtable → BigQuery with the contracts)

These are the schemas the `network` data contracts expect. Three contracts currently fail
`schema_required_columns` because the live Airtable-synced tables don't yet have these columns.
Create the fields below (in Airtable, or directly in BigQuery) and the contracts pass.

**Dataset:** `network` in YAML (override with `BQ_DATASET` for live Fivetran destination schema) · **Connector source:** Airtable · 5 tables.

> **Type note:** the validation engine normalizes BigQuery type aliases and treats the numeric
> family as compatible (`INTEGER ≡ INT64`, `FLOAT ≡ FLOAT64`, and `INT64/NUMERIC ↔ FLOAT64`). So
> a column only has to **exist** with the right name and be the right *family* — Airtable's
> Number fields (which Fivetran may land as `FLOAT64` or `NUMERIC`) satisfy the `INTEGER`/`FLOAT`
> contracts without manual casting. The hard requirement is the **column names**.

---

## 1. `cdr` — Call Detail Records
Governed by `network_cdr_schema_v1` (freshness 120 min, schema, volume, semantic) and
`network_cdr_freshness_v1` (freshness 30 min).

| Column | BigQuery type | Contract rule | Airtable field type | Example |
| ------ | ------------- | ------------- | ------------------- | ------- |
| `cdr_id` | `STRING` | required | Single line text (primary) | `cdr_1001` |
| `subscriber_id` | `STRING` | required | Single line text | `sub_0007` |
| `duration_seconds` | `INT64` | required, type `INTEGER` | Number (integer) | `182` |
| `bytes_transferred` | `INT64` | required, type `INTEGER` | Number (integer) | `40960` |
| `charge_amount` | `FLOAT64` | required, type `FLOAT`, **not null** | Currency / Number (decimal) | `0.42` |

Semantic check: `SELECT COUNT(*) FROM cdr WHERE charge_amount < 0` must be `0` → keep
`charge_amount >= 0`.

---

## 2. `data_session` — Data usage sessions (PDP)
Governed by `network_data_session_v1` (freshness 60 min, schema, volume).

| Column | BigQuery type | Contract rule | Airtable field type | Example |
| ------ | ------------- | ------------- | ------------------- | ------- |
| `session_id` | `STRING` | required | Single line text (primary) | `sess_50012` |
| `subscriber_id` | `STRING` | required | Single line text | `sub_0007` |
| `apn` | `STRING` | required | Single line text | `internet` |
| `rx_bytes` | `INT64` | required, type `INTEGER` | Number (integer) | `1048576` |
| `tx_bytes` | `INT64` | required, type `INTEGER` | Number (integer) | `262144` |
| `data_charge` | `FLOAT64` | required, type `FLOAT` | Currency / Number (decimal) | `0.15` |

---

## 3. `cell_tower` — Cell site inventory
Governed by `network_cell_tower_v1` (freshness 1440 min / daily, schema).

| Column | BigQuery type | Contract rule | Airtable field type | Example |
| ------ | ------------- | ------------- | ------------------- | ------- |
| `cell_id` | `STRING` | required | Single line text (primary) | `cell_2201` |
| `site_name` | `STRING` | required | Single line text | `LDN-Canary-01` |
| `latitude` | `FLOAT64` | required, type `FLOAT` | Number (decimal) | `51.5049` |
| `longitude` | `FLOAT64` | required, type `FLOAT` | Number (decimal) | `-0.0199` |
| `technology` | `STRING` | required | Single select | `5G` |
| `status` | `STRING` | required | Single select | `active` |

---

## 4. `network_alarm` — Network alarms / events
Governed by `network_alarm_v1` (freshness 15 min, schema). This is the tightest freshness
window — ideal as the demo's "hero" incident when the connector is slightly stale.

| Column | BigQuery type | Contract rule | Airtable field type | Example |
| ------ | ------------- | ------------- | ------------------- | ------- |
| `alarm_id` | `STRING` | required | Single line text (primary) | `alm_9001` |
| `cell_id` | `STRING` | required | Single line text | `cell_2201` |
| `severity` | `STRING` | required | Single select | `critical` |
| `raised_at` | `TIMESTAMP` | required | Date (with time) | `2026-06-07T09:05:00Z` |

---

## 5. `signal_sample` — Radio signal measurements
Governed by `network_signal_sample_v1` (freshness 120 min, schema, volume).

| Column | BigQuery type | Contract rule | Airtable field type | Example |
| ------ | ------------- | ------------- | ------------------- | ------- |
| `sample_id` | `STRING` | required | Single line text (primary) | `smp_77001` |
| `cell_id` | `STRING` | required | Single line text | `cell_2201` |
| `subscriber_id` | `STRING` | required | Single line text | `sub_0007` |
| `rsrp_dbm` | `FLOAT64` | required, type `FLOAT` | Number (decimal) | `-95.4` |
| `rsrq_db` | `FLOAT64` | required, type `FLOAT` | Number (decimal) | `-10.2` |
| `sampled_at` | `TIMESTAMP` | required | Date (with time) | `2026-06-07T09:10:00Z` |

---

## How to apply

### Option A — Airtable (recommended, keeps the live Fivetran pipeline)
1. In your Airtable base, create one table per schema above with **exactly these field names**
   (the primary field is the first one listed). The easiest way is to **import the CSVs** in
   [`seed/`](../seed/) — Airtable creates the fields from the header row.
2. Add a few rows (the CSVs include sample rows; keep `charge_amount >= 0`).
3. In Fivetran, ensure the connector syncs these tables, then trigger a sync. After the sync,
   `MOCK_BIGQUERY=false` validation reads the real `INFORMATION_SCHEMA` and the schema checks pass.

### Option B — BigQuery directly (skip Airtable, seed the warehouse)
Use the load script (creates the dataset + tables with the exact types and loads the CSV seeds):

```bash
PROJECT=your-gcp-project DATASET=network bash seed/load_bigquery.sh
```

### Freshness
Schema alignment fixes the `schema_required_columns` failures. **Freshness** is independent — a
table passes only if its last sync is within the contract's `max_delay_minutes`. Re-sync the
connector (or re-load the tables) right before a demo. Leaving `network_alarm` (15 min) slightly
stale gives you one genuine, well-grounded freshness incident to showcase.

See [FIVETRAN.md](./FIVETRAN.md) for connector + MCP setup and [`contracts/`](../contracts/) for
the authoritative rules.

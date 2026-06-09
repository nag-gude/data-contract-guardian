# Google Cloud Agent Builder (ADK) — Data Contract Guardian

## Architecture

```
Gemini (Vertex AI on GCP)
    ↓
Google Cloud Agent Builder (ADK Agent + InMemoryRunner)
    ↓
McpToolset (stdio) → github.com/fivetran/fivetran-mcp
    ↓
Investigation tools: get_connection_details, get_connection_state, get_connection_schema_config
    ↓
Evidence bundles → grounded RCA → HITL approval → remediation execution → verification
```

Production investigations run via FastAPI (`USE_AGENT_BUILDER=true` → `run_guardian_turn()` in `agent.py`). Local **`adk web agent_builder`** is for interactive chat testing.

## Local setup

```bash
cd backend
pip install -r requirements.txt
export PYTHONPATH=.

# Vertex AI (recommended)
export GCP_PROJECT_ID=prj-caiml-hackathon-01
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_PROJECT=$GCP_PROJECT_ID
export GOOGLE_CLOUD_LOCATION=us-central1
export GEMINI_MODEL=gemini-2.5-pro
export GEMINI_LOCATION=us-central1

# Live integrations
export MOCK_FIVETRAN_MCP=false
export MOCK_BIGQUERY=false
export BQ_DATASET=airtable_network_appxzsmwynqrvmfcq
export FIVETRAN_CONNECTION_ID=toll_donator
export FIVETRAN_API_KEY=...
export FIVETRAN_API_SECRET=...

gcloud auth application-default login   # if not already done

adk web agent_builder
```

### Gemini model regions

| Model | `GEMINI_LOCATION` |
| ----- | ----------------- |
| `gemini-2.5-flash` | `us-central1` (default) |
| `gemini-3.5-flash` | `global` (not available in `us-central1`) |

ADK auto-falls back to `GEMINI_FALLBACK_MODEL` when a `gemini-3.*` primary is set with a regional endpoint (`agent_builder/gemini_config.py`).

## MCP server

Cloud Run uses the bundled `fivetran-mcp` command. Locally:

```bash
uvx --from git+https://github.com/fivetran/fivetran-mcp fivetran-mcp
```

Configured via `FIVETRAN_MCP_COMMAND` and `FIVETRAN_MCP_ARGS`.

## Sample ADK web prompts

Copy-paste into the ADK chat UI.

### Freshness investigation (live pipeline)

```
Contract network_cdr_freshness_v1 failed validation.

Connector: ft_airtable_network (Fivetran connection toll_donator).
BigQuery: prj-caiml-hackathon-01.airtable_network_appxzsmwynqrvmfcq.cdr
Failed check: freshness.

1. Call get_connection_details, get_connection_state, get_connection_schema_config for toll_donator.
2. Call validate_data_contract for network_cdr_freshness_v1.
3. Compare Fivetran succeeded_at vs BigQuery age_minutes from checks[].
4. Propose ranked remediations — do not execute (human approval required).
```

### Connector health smoke test

```
Check Fivetran connector toll_donator: get_connection_details and get_connection_state.
Report paused, sync_state, succeeded_at. Then validate_data_contract for network_cdr_freshness_v1.
```

### Schema drift

```
For connection toll_donator, get_connection_schema_config and validate_data_contract for network_cdr_schema_v1.
List failed schema_type_* checks with expected vs actual types.
```

## What ADK web cannot do

* **Approve remediations** — use Guardian UI (Incidents → Approve) or `POST /api/incidents/approve-remediation`
* **Open incidents** — use `POST /api/agent/run-pipeline` or the UI pipeline button

Approval **executes** the top-ranked remediation (`remediation_executor.py`): mock freshness fix, or live Fivetran sync via REST, then re-validates with polling.

## Verify integrations

```bash
curl -s http://localhost:8000/api/agent/platform | jq '{
  adk: .agent_builder,
  gemini: .gemini,
  mcp: .fivetran_mcp,
  bq: .bigquery
}'
```

Expect `adk_installed: true`, `fivetran_mcp.transport: "stdio"`, `bigquery.mock_mode: false` when live.

## Related code

| File | Role |
| ---- | ---- |
| `agent_builder/agent.py` | ADK agent + `run_guardian_turn()` |
| `agent_builder/mcp_config.py` | `McpToolset` bridge |
| `agent_builder/gemini_config.py` | Vertex / AI Studio auth for ADK |
| `app/services/agent_orchestrator.py` | Production orchestration (ADK or deterministic fallback) |

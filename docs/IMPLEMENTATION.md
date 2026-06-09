# Implementation guide

This document describes how **Data Contract Guardian** is built: components, request flow, persistence, and where to extend behavior. It is aimed at engineers who will run, modify, or demo the system.

## High-level architecture

The system has two runnable parts:

1. **Backend** — Python **FastAPI** application exposing REST JSON APIs under `/api/...`.
2. **Frontend** — **Next.js 14** (App Router) UI. In production it exposes **same-origin** `/api/...` routes that **proxy** to the backend (see [Deployment](./DEPLOYMENT.md)).

Supporting assets:

* **`contracts/`** — YAML definitions of data contracts (schema, freshness, optional volume/semantic stubs).
* **SQLite** (default local path under `backend/data/`, or `/tmp` in container images) — incidents, evidence bundles, validation runs, mock warehouse state, approvals, resolution memory.

There is **no separate microservice** for the agent: orchestration lives in Python (`agent_orchestrator`, `agent_rca`, `incident_service`, `remediation_executor`) with a deterministic, step-stamped transcript and optional **Google Gemini** calls (Vertex AI, or an AI Studio `GEMINI_API_KEY`) for natural-language RCA. When `USE_AGENT_BUILDER=true` and `google-adk` is installed, investigations can run through the **Agent Builder (ADK)** agent in `agent_builder/`.

## Repository layout (implementation-focused)

| Path | Role |
| ---- | ---- |
| `backend/app/main.py` | FastAPI app, CORS, router mounting |
| `backend/app/config.py` | Pydantic settings from environment |
| `backend/app/db.py` | SQLite schema bootstrap and connection helper |
| `backend/app/schemas.py` | Pydantic models shared by routers and services |
| `backend/app/routers/` | HTTP route modules (`contracts`, `incidents`, `validation`, `demo`, `agent`) |
| `backend/app/services/` | Business logic: contracts loader, validation, Fivetran MCP, agent orchestrator, incidents, RCA, remediation execution |
| `backend/agent_builder/` | Google Cloud Agent Builder (ADK) agent definition |
| `frontend/app/` | Pages, `loading.tsx` skeletons, API route handlers |
| `frontend/middleware.ts` | Reverse proxy from Next to FastAPI when `BACKEND_URL` is set |
| `frontend/lib/api.ts`, `frontend/lib/platform.ts` | Server fetch helpers; platform status cached 15s via `unstable_cache` |
| `frontend/components/guardian/` | Agent pipeline, MCP discovery panel, system status, workflow stepper |
| `contracts/*.yaml` | Contract registry files read at runtime |

## Configuration (backend)

Settings are loaded via **`pydantic-settings`** (environment variables and optional `.env` next to the process cwd).

| Variable | Purpose |
| -------- | ------- |
| `CONTRACTS_DIR` | Directory containing contract YAML files (Docker: `/app/contracts`) |
| `DATABASE_PATH` | SQLite file path (Docker default: `/tmp/guardian.db`) |
| `CORS_ORIGINS` | Comma-separated origins, or `*` for wide-open demo |
| `GCP_PROJECT_ID` | GCP project for live BigQuery and Vertex AI Gemini |
| `BQ_DATASET` | Overrides contract placeholder `bq_dataset: network` with the live Fivetran destination slug |
| `GEMINI_MODEL` | Primary model id (default `gemini-2.5-flash` — GA in `us-central1`) |
| `GEMINI_FALLBACK_MODEL` | Secondary model when primary fails or is unavailable in region |
| `GEMINI_LOCATION` | Vertex AI region for Gemini (`us-central1` for 2.5; `global` for `gemini-3.5-*`) |
| `GEMINI_BACKEND` | `auto` \| `vertex` \| `ai_studio` |
| `GEMINI_API_KEY` | AI Studio key (local fallback when Vertex ADC unavailable) |
| `USE_AGENT_BUILDER` | When true, prefer ADK agent when `google-adk` is installed |
| `FIVETRAN_API_KEY` / `FIVETRAN_API_SECRET` | Live Fivetran MCP stdio (and REST sync on approval) |
| `FIVETRAN_CONNECTION_ID` | Dashboard slug (e.g. `toll_donator`) or hint resolved via `list_connections` |
| `FIVETRAN_MCP_COMMAND` / `FIVETRAN_MCP_ARGS` | Launch command for fivetran-mcp server |
| `FIVETRAN_ALLOW_WRITES` | MCP write tools (default `false`; approval uses Fivetran REST for sync) |
| `MOCK_FIVETRAN_MCP` | When true, use in-process mock instead of live MCP |
| `MOCK_BIGQUERY` | When false + `GCP_PROJECT_ID`, validate against live BigQuery |

### Contract env resolution (`contracts_loader.py`)

At load time, placeholders in YAML are rewritten:

| YAML placeholder | Env override |
| ---------------- | ------------ |
| `bq_project: demo-gcp-project` | `GCP_PROJECT_ID` |
| `bq_dataset: network` | `BQ_DATASET` |
| `fivetran_connector_id: hackathon` (misconfigured hint) | Maps to alias `ft_airtable_network` |

Connector alias `ft_airtable_network` is resolved to a real Fivetran connection slug via `fivetran_connection_resolver.py` (`list_connections`, env hint, or sole-Airtable fallback).

## Data contracts (YAML)

Each contract file is validated into a **`DataContract`** model. Important fields:

* `contract_id` — stable id used for mock warehouse state and incidents.
* `fivetran_connector_id` — connector ref for MCP (often `ft_airtable_network`).
* `bq_project`, `bq_dataset`, `bq_table` — BigQuery target for live validation.

The YAML key **`schema`** maps to the Python field **`schema_block`**.

## Warehouse validation (mock or live BigQuery)

**Mock path** (`MOCK_BIGQUERY=true`, default):

* **`mock_warehouse_state`** SQLite table stores JSON per `contract_id`.
* Demo seeders set passing/failing state per contract.

**Live path** (`MOCK_BIGQUERY=false` + `GCP_PROJECT_ID`):

* `bigquery_validation.py` reads `INFORMATION_SCHEMA.COLUMNS` and `__TABLES__.last_modified`.
* Semantic SQL rules run as BigQuery jobs.
* Set **`BQ_DATASET`** to the Fivetran destination schema slug when YAML still says `network`.

Setup: [FIVETRAN.md](./FIVETRAN.md).

## Fivetran MCP (mock + live stdio)

`fivetran_mcp_stdio.py` speaks **Model Context Protocol** over stdio to [fivetran/fivetran-mcp](https://github.com/fivetran/fivetran-mcp).

**Investigation tools** (per failed contract):

* `get_connection_details`
* `get_connection_state` (405 on standard connectors → enriched from details)
* `get_connection_schema_config`

**Discovery tools** (`POST /api/agent/mcp-discovery`, five tools in one batched stdio session when live):

* `get_account_info`, `list_connections`, `get_connection_details`, `get_connection_state`, `list_destinations`

Every tool call includes mandatory **`schema_file`** (OpenAPI path). Evidence bundles are persisted on incidents.

ADK uses `McpToolset` in `agent_builder/mcp_config.py` for the same server.

## Agent orchestrator (Agent Builder pattern)

`agent_orchestrator.py` runs:

**PLAN** → **MCP tools** → **validate** → **SYNTH** (RCA) → **PROPOSE** (evidence-aware ARP) → **AWAIT**

When ADK is available, `agent_builder/agent.py` (`run_guardian_turn`) runs the same mission via `InMemoryRunner` + `McpToolset`.

### Evidence-aware remediations (`agent_rca.py`)

Ranked remediations depend on failing check types **and** MCP evidence:

| Failure | Remediation (examples) |
| ------- | ---------------------- |
| `schema_type_*` | Per-column SAFE_CAST MR proposal |
| `freshness` + connector paused | Resume sync (R4) |
| `freshness` + connector healthy | Manual sync / ingestion lag investigation (R3) |
| Unknown | GitHub issue coordination (R2) |

## Human approval and remediation execution

`incident_service.approve_remediation()`:

1. Validates `action_fingerprint` and optional `idempotency_key`.
2. Records approval; optional Slack webhook.
3. **Executes** the top-ranked remediation via `remediation_executor.py`:
   * **Sync remediations (mock):** refreshes `last_synced_at` in mock warehouse.
   * **Sync remediations (live):** triggers Fivetran sync via `fivetran_rest.py` (REST API, not MCP writes).
   * **Schema remediations (mock):** corrects drifted column types.
   * **Advisory (GitHub issue):** no automated warehouse change.
4. **Re-validates** with `verify_with_retry()` — polls up to ~90s after live sync for BigQuery freshness.
5. Sets **`resolved`** or **`awaiting_approval`** with `remediation_status: verify_failed`.

Approval is **only** via UI or `POST /api/incidents/approve-remediation` (not agent chat APIs).

## Data model (SQLite)

All state lives in a single SQLite file. Cloud Run backend is pinned to **`max_instance_count = 1`** so incidents and platform workflow counters stay consistent across requests.

Open incident statuses: `awaiting_approval`, `executing`, `verify_failed`.

## Incident lifecycle

1. Validation fails → agent investigation → incident **`awaiting_approval`** with evidence + fingerprint.
2. Operator approves → **`executing`** → remediation side effect → re-validation.
3. Pass → **`resolved`**; fail → **`awaiting_approval`** / **`verify_failed`** (re-approve after upstream fix).

## REST API summary

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/health` | Liveness |
| GET | `/api/agent/platform` | Integration + workflow counters (lightweight; no MCP spawn) |
| POST | `/api/agent/mcp-discovery` | Five read-only Fivetran discovery tools |
| POST | `/api/agent/discover/{contract_id}` | Validate + investigate; no incident |
| POST | `/api/agent/investigate` | Agent investigation for one contract |
| POST | `/api/agent/run-pipeline` | Validate all + agent + open incidents |
| GET | `/api/incidents` | List incidents (`?open=true` for open only) |
| GET | `/api/incidents/{id}` | Incident detail + transcript + evidence |
| POST | `/api/incidents/approve-remediation` | Approve/reject + execute + verify |
| POST | `/api/approve-remediation` | Alias of above |
| POST | `/api/validation/run` | Run validation for all contracts |
| GET | `/api/validation/results` | Recent validation runs (`?per_contract=true`) |
| Demo routes | `/api/demo/*` | Seed mock warehouse, prune duplicates |

Interactive docs: **`/docs`** (Swagger UI).

## Frontend behavior

* **Agent Home** loads platform status on the server; **MCP discovery runs client-side** in `PipelineDiscoveryPanel` (does not block initial page render).
* **`loading.tsx`** provides skeleton UI during server fetches.
* After pipeline/approval/demo actions, UI uses **`router.refresh()`** instead of full page reload.
* Browser calls **`/api/...`** → Next proxy → FastAPI when **`BACKEND_URL`** is set.

## Testing and quality

```bash
cd backend && python -m pytest
cd frontend && npm run build
cd terraform && terraform validate
```

## Extension checklist

1. **Live Fivetran → BigQuery** — [FIVETRAN.md](./FIVETRAN.md); set `MOCK_BIGQUERY=false`, `BQ_DATASET`, connector id.
2. **Durable state** — replace SQLite with Cloud SQL / AlloyDB for multi-instance Cloud Run.
3. **Additional remediation types** — extend `remediation_executor.py` (dbt MR hooks, GitHub issues).

## Security notes

* Do not commit **`.env`**, **`terraform.tfvars`**, or service account JSON.
* Prefer `TF_VAR_fivetran_api_key` / `TF_VAR_fivetran_api_secret` over plaintext in tfvars.
* `FIVETRAN_ALLOW_WRITES=false` for MCP; sync on approval uses scoped REST calls from the backend.

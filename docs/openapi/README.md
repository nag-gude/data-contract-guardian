# Agent API (OpenAPI)

Read-only HTTP surface for **Google ADK** chat agents and **Vertex Agent Engine** — investigation and discovery only. Approval and remediation stay in the web UI.

**Spec:** [agent-api.yaml](./agent-api.yaml)

**Live base URL:** `https://data-contract-guardian-api-920722415791.us-central1.run.app`

---

## Endpoints

| Method | Path | Purpose |
| ------ | ---- | ------- |
| GET | `/api/agent/platform` | Integration status + workflow counters |
| POST | `/api/agent/discover/{contract_id}` | Validate + investigate (no incident open) |
| POST | `/api/agent/mcp-discovery` | Five read-only Fivetran discovery tools |
| POST | `/api/agent/fivetran` | Proxy single Fivetran MCP tool (Agent Engine path) |
| POST | `/api/agent/investigate` | Full investigation (optional incident) |
| POST | `/api/agent/run-pipeline` | Validate all + agent + open incidents |

**Not exposed to chat:** `POST /api/incidents/approve-remediation` — human gate only.

---

## Example: platform status

```bash
curl -s https://data-contract-guardian-api-920722415791.us-central1.run.app/api/agent/platform
```

---

## Example: discover contract

```bash
curl -s -X POST \
  "https://data-contract-guardian-api-920722415791.us-central1.run.app/api/agent/discover/network_cdr_freshness_v1" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Response includes `mcp_trace`, `summary_for_agent`, `ranked_remediations`, `failed_checks`.

---

## ADK integration

The standalone chat agent (`guardian-adk/guardian_assistant/agent.py`) wraps these endpoints as FunctionTools:

* `guardianPlatformStatus()` → GET `/api/agent/platform`
* `guardianDiscoverContract(id)` → POST `/api/agent/discover/{id}`
* `guardianMcpDiscovery(ref)` → POST `/api/agent/mcp-discovery`
* Fivetran tools → POST `/api/agent/fivetran`

See [agent-builder-setup.md](../agent-builder-setup.md).

---

## Importing into Agent Builder Studio

If your console supports **OpenAPI tool import**, paste `agent-api.yaml` and use instructions from `guardian-adk/guardian_assistant/instructions.txt`.

If Studio only offers MCP / built-ins, use **ADK** (`adk web guardian-adk`) or **Agent Engine** deploy instead.

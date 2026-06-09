# Documentation

Project documentation for **implementation**, **deployment**, and **operations**. Start here, then open the guides below.

| Guide | Description |
| ----- | ----------- |
| [Fivetran & BigQuery setup](./FIVETRAN.md) | Airtable → BigQuery ingestion, `BQ_DATASET` override, live validation, MCP server |
| [Implementation](./IMPLEMENTATION.md) | Architecture, APIs, remediation execution, evidence-aware ARP, frontend performance |
| [Deployment](./DEPLOYMENT.md) | Local dev, ADK web, Docker, Terraform + Cloud Run, Gemini model regions, troubleshooting |
| [Agent Builder (ADK)](../backend/agent_builder/README.md) | `adk web agent_builder`, sample prompts, Vertex config |
| [Agent API (OpenAPI)](./openapi/agent-api.yaml) | Read-only agent surface for Agent Builder import |

## Quick links

* Root [README](../README.md) — short quick start and repo map  
* [`.env.example`](../.env.example) — environment variable templates  
* [Deploy Dockerfiles](../deploy/) — `Dockerfile.backend`, `Dockerfile.frontend`  
* [Terraform](../terraform/) — GCP infrastructure as code  

## License

See [LICENSE](../LICENSE) in the repository root.

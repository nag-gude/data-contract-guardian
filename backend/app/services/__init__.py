"""Service layer for Data Contract Guardian.

Stateless, router-agnostic business logic: contract loading and validation
(``contracts_loader``, ``validation_engine``, ``bigquery_validation``), Fivetran MCP
investigation (``fivetran_mcp``, ``fivetran_mcp_stdio``), Gemini reasoning
(``gemini_client``, ``agent_rca``), the multi-step orchestrator and its tools
(``agent_orchestrator``, ``agent_tools``), and incident lifecycle plus human-in-the-loop
remediation (``incident_service``).
"""
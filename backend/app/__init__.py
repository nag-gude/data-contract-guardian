"""Data Contract Guardian — FastAPI backend package.

An operational AI agent for Fivetran → BigQuery data-pipeline reliability. The package wires
together the HTTP API (``main``), configuration (``config``), persistence (``db``), shared
Pydantic models (``schemas``), HTTP ``routers``, and the ``services`` layer that performs
contract validation, Fivetran MCP investigation, Gemini-grounded RCA, and human-approved
remediation with re-verification.
"""